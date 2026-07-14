#!/usr/bin/env python3
"""
将审批清单中的 approved 标的打包为执行手册 Prompt 输入。

输入：
- A_Share_Reports/candidate_pool_approval_sheet.json

输出：
- A_Share_Reports/approved_prompt_input.json
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from config.runtime import REPORT_DIR, setup_logger

logger = setup_logger("build_approved_prompt_input")

APPROVAL_SHEET = REPORT_DIR / "candidate_pool_approval_sheet.json"
OUTPUT_FILE = REPORT_DIR / "approved_prompt_input.json"
SCHEMA_VERSION = "approved.prompt.v1"


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"未找到文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = data.get("candidates", [])

    approved_items: List[Dict[str, Any]] = []
    for item in candidates:
        if str(item.get("approval_status", "pending")).lower() != "approved":
            continue

        approved_items.append(
            {
                "ts_code": item.get("ts_code"),
                "name": item.get("name"),
                "industry": item.get("industry"),
                "market": item.get("market"),
                "final_score": item.get("final_score"),
                "approval_note": item.get("approval_note"),
                "target_buy_zone": item.get("target_buy_zone"),
                "initial_stop_loss": item.get("initial_stop_loss"),
                "first_tranche_amount": item.get("first_tranche_amount"),
                "metrics_snapshot": {
                    "latest_close": item.get("latest_close"),
                    "ma60": item.get("ma60"),
                    "ma120": item.get("ma120"),
                    "avg_amount_20d": item.get("avg_amount_20d"),
                    "net_mf_amount_20d": item.get("net_mf_amount_20d"),
                    "trend_score": item.get("trend_score"),
                    "fund_flow_score": item.get("fund_flow_score"),
                    "liquidity_score": item.get("liquidity_score"),
                },
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_file": str(APPROVAL_SHEET),
        "summary": {
            "total_candidates": len(candidates),
            "approved_count": len(approved_items),
        },
        "approved_candidates": approved_items,
        "prompt_instruction": "请依据《2.0 战术执行手册》对 approved_candidates 逐一给出 GO/HOLD/REJECT、买入区间、止损位、首注仓位建议。",
    }


def main() -> None:
    data = load_json(APPROVAL_SHEET)
    payload = build_payload(data)
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("已生成执行手册输入包: %s", OUTPUT_FILE)


if __name__ == "__main__":
    main()
