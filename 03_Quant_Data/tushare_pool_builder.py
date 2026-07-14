#!/usr/bin/env python3
"""
A股候选股票池构建器（Tushare）

目标：
1) 仅构建当前可执行池（默认排除科创板688、创业板300）
2) 结合流动性/趋势/资金面做硬过滤 + 打分排序
3) 输出待审批股票池 candidate_pool_pending_review.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import tushare as ts
import tushare.pro.client as client

from config.runtime import REPORT_DIR, setup_logger
from config.secrets import TUSHARE_TOKEN

logger = setup_logger("tushare_pool_builder")

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "config" / "settings.json"
SETTINGS = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("akshare_stock_upgrade", {})

TOP_N = int(SETTINGS.get("pool_top_n", 30))
MIN_DAILY_AMOUNT = float(SETTINGS.get("pool_min_daily_amount", 1e7))
EXCLUDE_CHINEXT = bool(SETTINGS.get("exclude_chinext", True))
EXCLUDE_STAR = bool(SETTINGS.get("exclude_star", True))
SCHEMA_VERSION = "pool.v3"
THEMES_PATH = REPORT_DIR / "themes.json"
MANUAL_BOOST_PATH = REPORT_DIR / "themes_manual_boost.json"


def init_client():
    if not TUSHARE_TOKEN or "YOUR_" in TUSHARE_TOKEN:
        raise RuntimeError("请先在 config/secrets.py 配置 TUSHARE_TOKEN")
    client.DataApi._DataApi__http_url = "http://api.quicksync.cn"
    return ts.pro_api(TUSHARE_TOKEN)


def to_num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def is_excluded_market(ts_code: str) -> Optional[str]:
    code = ts_code.split(".")[0]
    if EXCLUDE_STAR and code.startswith("688"):
        return "excluded_star_market"
    if EXCLUDE_CHINEXT and code.startswith("300"):
        return "excluded_chinext_market"
    return None


def fetch_base_universe(pro) -> pd.DataFrame:
    df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,industry,market")
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df = df[~df["name"].astype(str).str.contains("ST", case=False, na=False)]
    return df.reset_index(drop=True)


def fetch_daily_slice(pro, ts_code: str, days: int = 140) -> pd.DataFrame:
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
    df = pro.daily(ts_code=ts_code, start_date=start, end_date=end)
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"], format="%Y%m%d", errors="coerce")
    out = out.sort_values("trade_date").tail(days).reset_index(drop=True)
    return out


def fetch_moneyflow_20d(pro, ts_code: str) -> Optional[float]:
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=50)).strftime("%Y%m%d")
    try:
        df = pro.moneyflow(ts_code=ts_code, start_date=start, end_date=end, fields="trade_date,net_mf_amount")
    except Exception:
        return None
    if df is None or df.empty or "net_mf_amount" not in df.columns:
        return None
    tmp = pd.to_numeric(df["net_mf_amount"], errors="coerce").dropna().tail(20)
    if tmp.empty:
        return None
    return float(tmp.sum())


def calc_metrics(daily: pd.DataFrame) -> Dict[str, Optional[float]]:
    if daily is None or daily.empty:
        return {"close": None, "ma60": None, "ma120": None, "trend_score": None, "avg_amount": None}

    close = pd.to_numeric(daily["close"], errors="coerce")
    amount = pd.to_numeric(daily["amount"], errors="coerce")

    ma60 = close.rolling(60).mean()
    ma120 = close.rolling(120).mean()

    last_close = to_num(close.iloc[-1])
    last_ma60 = to_num(ma60.iloc[-1])
    last_ma120 = to_num(ma120.iloc[-1])

    score = 0.0
    if last_close and last_ma60 and last_close > last_ma60:
        score += 40
    if last_ma60 and last_ma120 and last_ma60 > last_ma120:
        score += 30

    ma60_recent = ma60.dropna().tail(10)
    if len(ma60_recent) >= 10:
        slope = np.polyfit(np.arange(len(ma60_recent)), ma60_recent.values.astype(float), 1)[0]
        if slope > 0:
            score += 30

    avg_amount = to_num(amount.tail(20).mean())

    return {
        "close": last_close,
        "ma60": last_ma60,
        "ma120": last_ma120,
        "trend_score": score,
        "avg_amount": avg_amount,
    }


def load_manual_boost_weights() -> Tuple[Dict[str, float], Dict[str, Any]]:
    if not MANUAL_BOOST_PATH.exists():
        return {}, {"enabled": False, "reason": "themes_manual_boost.json not found"}

    try:
        payload = json.loads(MANUAL_BOOST_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return {}, {"enabled": False, "reason": f"manual boost parse error: {e}"}

    tracks = payload.get("tracks", []) if isinstance(payload, dict) else []
    if not tracks:
        return {}, {"enabled": False, "reason": "manual boost tracks empty"}

    weights: Dict[str, float] = {}
    for t in tracks:
        track = str(t.get("track", "")).strip()
        if not track:
            continue
        w = float(t.get("weight", 1.0) or 1.0)
        # 手工权重也做边界保护
        weights[track] = round(max(0.85, min(1.25, w)), 3)

    return weights, {
        "enabled": True,
        "track_count": len(weights),
        "generated_at": payload.get("generated_at"),
    }


def load_theme_weights() -> Tuple[Dict[str, float], Dict[str, Any]]:
    if not THEMES_PATH.exists():
        return {}, {"enabled": False, "reason": "themes.json not found"}

    try:
        payload = json.loads(THEMES_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return {}, {"enabled": False, "reason": f"themes.json parse error: {e}"}

    themes = payload.get("themes", []) if isinstance(payload, dict) else []
    if not themes:
        return {}, {"enabled": False, "reason": "themes empty"}

    max_signal = max(float(x.get("signal_count", 0) or 0) for x in themes) or 1.0
    weights: Dict[str, float] = {}
    for t in themes:
        track = str(t.get("track", "")).strip()
        if not track:
            continue
        avg_conf = float(t.get("avg_confidence", 0) or 0)
        signal = float(t.get("signal_count", 0) or 0)
        raw = 0.6 * avg_conf + 0.4 * (signal / max_signal)
        # 主题权重压到 0.8~1.2 区间，避免喧宾夺主
        weights[track] = round(0.8 + 0.4 * max(0.0, min(1.0, raw)), 3)

    return weights, {
        "enabled": True,
        "theme_count": len(weights),
        "generated_at": payload.get("generated_at"),
    }


def infer_track_from_stock(row) -> str:
    market = str(getattr(row, "market", "") or "")
    industry = str(getattr(row, "industry", "") or "")

    # 轻量映射：先用 market，再辅以 industry 关键词
    if "科创" in market:
        return "AI_Compute_Core"

    ind = industry.lower()
    if any(k in ind for k in ["医药", "生物", "医疗"]):
        return "Innovative_Drugs"
    if any(k in ind for k in ["电子", "半导体", "通信", "计算机"]):
        return "High_Speed_Interconnect"
    if any(k in ind for k in ["机械", "电气设备", "自动化"]):
        return "Humanoid_Robotics"
    if any(k in ind for k in ["军工", "航空", "航天"]):
        return "Low_Altitude_eVTOL"

    return ""


def build_candidate_pool(top_n: Optional[int] = None) -> Dict[str, Any]:
    pro = init_client()
    base = fetch_base_universe(pro)
    if base.empty:
        raise RuntimeError("stock_basic 返回为空，无法构建股票池")

    theme_weights, theme_meta = load_theme_weights()
    manual_weights, manual_meta = load_manual_boost_weights()

    records: List[Dict[str, Any]] = []
    for row in base.itertuples(index=False):
        ts_code = str(row.ts_code)
        name = str(row.name)

        reason = is_excluded_market(ts_code)
        if reason:
            continue

        try:
            daily = fetch_daily_slice(pro, ts_code, days=140)
            m = calc_metrics(daily)

            mf20 = fetch_moneyflow_20d(pro, ts_code)
            flow_score = 50.0
            if mf20 is not None:
                flow_score = 100.0 if mf20 > 0 else 40.0

            trend_score = m["trend_score"] or 0.0
            avg_amount = m["avg_amount"] or 0.0
            liquidity_score = max(0.0, min(100.0, (avg_amount / max(MIN_DAILY_AMOUNT, 1.0)) * 100.0))
            amount_score = 0.0
            if avg_amount >= MIN_DAILY_AMOUNT:
                amount_score = 100.0
            elif avg_amount > 0:
                amount_score = max(15.0, (avg_amount / MIN_DAILY_AMOUNT) * 100.0)
            base_score = 0.5 * trend_score + 0.2 * flow_score + 0.2 * liquidity_score + 0.1 * amount_score

            inferred_track = infer_track_from_stock(row)
            auto_weight = theme_weights.get(inferred_track, 0.9 if theme_meta.get("enabled") else 1.0)
            manual_weight = manual_weights.get(inferred_track, 1.0)
            combined_weight = round(auto_weight * manual_weight, 3)
            combined_weight = max(0.8, min(1.3, combined_weight))
            theme_boost = 15.0 * (combined_weight - 1.0)

            final_score = round(base_score * combined_weight + theme_boost, 2)

            records.append(
                {
                    "ts_code": ts_code,
                    "name": name,
                    "industry": str(getattr(row, "industry", "")),
                    "market": str(getattr(row, "market", "")),
                    "latest_close": m["close"],
                    "ma60": m["ma60"],
                    "ma120": m["ma120"],
                    "avg_amount_20d": m["avg_amount"],
                    "net_mf_amount_20d": mf20,
                    "trend_score": round(trend_score, 2),
                    "fund_flow_score": round(flow_score, 2),
                    "liquidity_score": round(liquidity_score, 2),
                    "base_score": round(base_score, 2),
                    "theme_track": inferred_track,
                    "theme_weight_auto": auto_weight,
                    "theme_weight_manual": manual_weight,
                    "theme_weight_combined": combined_weight,
                    "theme_boost": round(theme_boost, 2),
                    "final_score": final_score,
                    "approval_status": "pending",
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("跳过 %s(%s): %s", name, ts_code, e)

    records.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    selected_n = TOP_N if top_n is None else max(1, int(top_n))
    selected = records[:selected_n]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filters": {
            "exclude_star": EXCLUDE_STAR,
            "exclude_chinext": EXCLUDE_CHINEXT,
            "min_daily_amount": MIN_DAILY_AMOUNT,
            "top_n": TOP_N,
        },
        "theme_overlay": {
            "auto": {
                **theme_meta,
                "weights": theme_weights,
            },
            "manual": {
                **manual_meta,
                "weights": manual_weights,
            },
        },
        "summary": {
            "candidates_total": len(records),
            "selected_count": len(selected),
        },
        "candidates": selected,
    }
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tushare 候选池构建器")
    parser.add_argument("--top-n", type=int, default=None, help="覆盖配置中的候选数量")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_candidate_pool(top_n=args.top_n)
    out_path = REPORT_DIR / "candidate_pool_pending_review.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("已输出候选池: %s", out_path)


if __name__ == "__main__":
    main()
