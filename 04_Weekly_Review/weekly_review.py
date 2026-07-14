#!/usr/bin/env python3
"""
周度复盘工具（04_Weekly_Review）

输入：
- week_config.json（周参数）
- week_start_positions.json（周初持仓）
- week_end_positions.json（周末持仓）
- week_trades.csv（本周交易流水）

输出：
- weekly_review_report.json
- weekly_review_report.md
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent
OUT_JSON = BASE_DIR / "weekly_review_report.json"
OUT_MD = BASE_DIR / "weekly_review_report.md"


@dataclass
class Position:
    ts_code: str
    shares: float
    price: float

    @property
    def market_value(self) -> float:
        return self.shares * self.price


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_positions(path: Path) -> Dict[str, Position]:
    payload = load_json(path)
    positions = {}
    for row in payload.get("positions", []):
        code = str(row.get("ts_code", "")).strip().upper()
        if not code:
            continue
        positions[code] = Position(
            ts_code=code,
            shares=float(row.get("shares", 0) or 0),
            price=float(row.get("price", 0) or 0),
        )
    return positions


def load_trades(path: Path) -> List[Dict[str, Any]]:
    out = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            out.append(r)
    return out


def load_execution_rows() -> List[Dict[str, Any]]:
    approval_path = Path(__file__).resolve().parent.parent / "03_Quant_Data" / "A_Share_Reports" / "candidate_pool_approval_sheet.json"
    if not approval_path.exists():
        return []
    try:
        payload = json.loads(approval_path.read_text(encoding="utf-8"))
        return list(payload.get("rows", []))
    except Exception:
        return []


def portfolio_value(positions: Dict[str, Position]) -> float:
    return sum(p.market_value for p in positions.values())


def build_review() -> Dict[str, Any]:
    cfg = load_json(BASE_DIR / "week_config.json")
    start_pos = load_positions(BASE_DIR / "week_start_positions.json")
    end_pos = load_positions(BASE_DIR / "week_end_positions.json")
    trades = load_trades(BASE_DIR / "week_trades.csv")

    start_cash = float(cfg.get("week_start_cash", 0) or 0)
    end_cash = float(cfg.get("week_end_cash", 0) or 0)

    start_total = start_cash + portfolio_value(start_pos)
    end_total = end_cash + portfolio_value(end_pos)

    weekly_ret = (end_total / start_total - 1) if start_total > 0 else 0

    bm = cfg.get("benchmark", {}) if isinstance(cfg.get("benchmark", {}), dict) else {}
    hs300_ret = float(bm.get("hs300_weekly_return", 0) or 0)
    csi_div_ret = float(bm.get("csi_dividend_weekly_return", 0) or 0)
    excess_vs_hs300 = weekly_ret - hs300_ret
    excess_vs_csi_div = weekly_ret - csi_div_ret

    stop_loss_trades = sum(1 for t in trades if str(t.get("action", "")).lower() == "sell" and "stop" in str(t.get("reason", "")).lower())
    manual_override = sum(1 for t in trades if "override" in str(t.get("reason", "")).lower())

    execution_rows = load_execution_rows()
    execution_summary = {
        "not_sent": 0,
        "sent": 0,
        "filled": 0,
        "cancelled": 0,
    }
    for row in execution_rows:
        st = str(row.get("execution_status", "")).strip().lower()
        if st in execution_summary:
            execution_summary[st] += 1

    discipline_score = 100
    discipline_score -= min(30, manual_override * 10)
    discipline_score -= min(20, max(0, len(trades) - int(cfg.get("max_weekly_trades", 8))) * 5)
    discipline_score = max(0, discipline_score)

    health = "healthy"
    if weekly_ret < -0.03 or discipline_score < 70:
        health = "needs_adjustment"
    elif weekly_ret < 0 or discipline_score < 85:
        health = "watch"

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "week": cfg.get("week_label", "unknown"),
        "summary": {
            "start_total": round(start_total, 2),
            "end_total": round(end_total, 2),
            "weekly_return": round(weekly_ret, 4),
            "benchmark": {
                "hs300_weekly_return": round(hs300_ret, 4),
                "csi_dividend_weekly_return": round(csi_div_ret, 4),
                "excess_vs_hs300": round(excess_vs_hs300, 4),
                "excess_vs_csi_dividend": round(excess_vs_csi_div, 4)
            },
            "trade_count": len(trades),
            "stop_loss_trades": stop_loss_trades,
            "manual_override_count": manual_override,
            "discipline_score": discipline_score,
            "health": health,
            "execution_summary": execution_summary,
        },
        "suggestions": [
            "仅交易审批为 GO 的标的，避免临盘主观加单。",
            "若周回撤超过3%，下周首注仓位降到8%。",
            "每笔交易必须填写 reason，周末复盘校验是否符合计划。",
        ],
    }


def to_markdown(report: Dict[str, Any]) -> str:
    s = report["summary"]
    return "\n".join([
        f"# Weekly Review - {report['week']}",
        "",
        f"- Start Total: {s['start_total']}",
        f"- End Total: {s['end_total']}",
        f"- Weekly Return: {s['weekly_return']:.2%}",
        f"- HS300 Return: {s['benchmark']['hs300_weekly_return']:.2%}",
        f"- CSI Dividend Return: {s['benchmark']['csi_dividend_weekly_return']:.2%}",
        f"- Excess vs HS300: {s['benchmark']['excess_vs_hs300']:.2%}",
        f"- Excess vs CSI Dividend: {s['benchmark']['excess_vs_csi_dividend']:.2%}",
        f"- Trade Count: {s['trade_count']}",
        f"- Stop-Loss Trades: {s['stop_loss_trades']}",
        f"- Manual Overrides: {s['manual_override_count']}",
        f"- Discipline Score: {s['discipline_score']}",
        f"- Health: {s['health']}",
        "",
        "## Suggestions",
        *[f"- {x}" for x in report.get("suggestions", [])],
    ])


def main() -> None:
    report = build_review()
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(to_markdown(report), encoding="utf-8")
    print(f"[OK] weekly review generated -> {OUT_JSON}")


if __name__ == "__main__":
    main()
