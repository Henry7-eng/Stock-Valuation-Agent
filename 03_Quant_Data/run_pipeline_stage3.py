#!/usr/bin/env python3
"""
阶段3总入口 Runner
一条命令串联：建池 -> 拉阶段3数据 -> 生成审批清单
并支持 run_id 产物归档与数据新鲜度检查。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from config.runtime import REPORT_DIR

PROJECT_ROOT = Path(__file__).resolve().parent.parent
THEMES_PATH = REPORT_DIR / "themes.json"
POOL_PATH = REPORT_DIR / "candidate_pool_pending_review.json"
APPROVAL_PATH = REPORT_DIR / "candidate_pool_approval_sheet.json"
SUMMARY_PATH = REPORT_DIR / "stage3_pipeline_summary.json"
RUNS_DIR = REPORT_DIR / "runs"


def run_cmd(cmd: List[str]) -> Dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, env=env)
    return {
        "cmd": " ".join(cmd),
        "returncode": p.returncode,
        "stdout": p.stdout[-4000:],
        "stderr": p.stderr[-4000:],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="阶段3总入口")
    parser.add_argument("--top-n", type=int, default=None, help="候选池输出数量（可选）")
    parser.add_argument("--with-themes", action="store_true", help="先从 VIP 文本提取 themes.json")
    return parser.parse_args()


def build_approval_sheet(pool_payload: Dict[str, Any]) -> Dict[str, Any]:
    rows = []
    for item in pool_payload.get("candidates", []):
        rows.append(
            {
                "ts_code": item.get("ts_code"),
                "name": item.get("name"),
                "industry": item.get("industry"),
                "final_score": item.get("final_score"),
                "approval_status": "pending",
                "approval_note": "",
                "execution_status": "not_sent",
                "execution_price": "",
                "execution_time": "",
                "risk_level": "",
                "invalid_if": "",
                "target_buy_zone": "",
                "initial_stop_loss": "",
                "first_tranche_amount": "",
            }
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": str(POOL_PATH),
        "rows": rows,
    }


def check_data_freshness() -> Dict[str, Any]:
    alerts: List[str] = []
    now = datetime.now()

    if THEMES_PATH.exists():
        mtime = datetime.fromtimestamp(THEMES_PATH.stat().st_mtime)
        if now - mtime > timedelta(days=3):
            alerts.append("themes.json older than 3 days")

    if POOL_PATH.exists():
        mtime = datetime.fromtimestamp(POOL_PATH.stat().st_mtime)
        if now - mtime > timedelta(days=2):
            alerts.append("candidate pool older than 2 days")

    return {
        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "is_fresh": len(alerts) == 0,
        "alerts": alerts,
    }


def archive_outputs(run_id: str) -> Dict[str, str]:
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    copied: Dict[str, str] = {}
    candidates = {
        "themes.json": THEMES_PATH,
        "candidate_pool_pending_review.json": POOL_PATH,
        "candidate_pool_approval_sheet.json": APPROVAL_PATH,
        "akshare_stock_upgrade_output.json": REPORT_DIR / "akshare_stock_upgrade_output.json",
        "stage3_pipeline_summary.json": SUMMARY_PATH,
    }

    for name, src in candidates.items():
        if src.exists():
            dst = run_dir / name
            shutil.copy2(src, dst)
            copied[name] = str(dst)

    return copied


def build_retry_summary(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    failed_steps = [s for s in steps if int(s.get("returncode", 1)) != 0]
    if not failed_steps:
        return {
            "failed_step_count": 0,
            "most_failed_step": None,
            "failed_stocks": [],
            "suggested_retry_commands": [],
        }

    name_count: Dict[str, int] = {}
    for s in failed_steps:
        step_name = str(s.get("cmd", "")).split(" ")[1] if " " in str(s.get("cmd", "")) else str(s.get("cmd", ""))
        name_count[step_name] = name_count.get(step_name, 0) + 1

    most_failed_step = max(name_count.items(), key=lambda x: x[1])[0]

    failed_stocks: List[str] = []
    for s in failed_steps:
        msg = f"{s.get('stdout', '')}\n{s.get('stderr', '')}"
        for line in msg.splitlines():
            if "失败:" in line and "(" in line and ")" in line:
                # 兼容日志格式: 失败: 名称(代码)
                l = line.strip()
                if l not in failed_stocks:
                    failed_stocks.append(l)

    retry_cmds = [s.get("cmd") for s in failed_steps if s.get("cmd")]

    return {
        "failed_step_count": len(failed_steps),
        "most_failed_step": most_failed_step,
        "failed_stocks": failed_stocks,
        "suggested_retry_commands": retry_cmds,
    }


def main() -> None:
    args = parse_args()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    results = []

    if args.with_themes:
        results.append(run_cmd([sys.executable, "-m", "03_Quant_Data.extract_themes_from_vip"]))
        if results[-1]["returncode"] != 0:
            SUMMARY_PATH.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "steps": results,
                        "retry_summary": build_retry_summary(results),
                        "status": "failed_at_themes",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise SystemExit("themes 提取失败，请先检查 stage3_pipeline_summary.json")

    cmd_pool = [sys.executable, "-m", "03_Quant_Data.tushare_pool_builder"]
    if args.top_n is not None:
        cmd_pool.extend(["--top-n", str(args.top_n)])
    results.append(run_cmd(cmd_pool))

    if results[-1]["returncode"] != 0:
        SUMMARY_PATH.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "steps": results,
                    "retry_summary": build_retry_summary(results),
                    "status": "failed_at_pool",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise SystemExit("候选池构建失败，请先检查 stage3_pipeline_summary.json")

    results.append(run_cmd([sys.executable, "-m", "03_Quant_Data.akshare_stock_upgrade"]))

    if not POOL_PATH.exists():
        SUMMARY_PATH.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "steps": results,
                    "retry_summary": build_retry_summary(results),
                    "status": "missing_pool_file",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise SystemExit("未找到 candidate_pool_pending_review.json")

    pool_payload = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    approval = build_approval_sheet(pool_payload)
    APPROVAL_PATH.write_text(json.dumps(approval, ensure_ascii=False, indent=2), encoding="utf-8")

    freshness = check_data_freshness()

    summary = {
        "run_id": run_id,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "ok",
        "freshness": freshness,
        "retry_summary": build_retry_summary(results),
        "steps": results,
        "outputs": {
            "themes": str(THEMES_PATH) if args.with_themes else None,
            "pool": str(POOL_PATH),
            "approval_sheet": str(APPROVAL_PATH),
            "stage3_data": str(REPORT_DIR / "akshare_stock_upgrade_output.json"),
        },
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    archived = archive_outputs(run_id)
    print(f"[OK] pipeline done -> {SUMMARY_PATH}")
    print(f"[OK] run_id={run_id} archived_files={len(archived)}")


if __name__ == "__main__":
    main()
