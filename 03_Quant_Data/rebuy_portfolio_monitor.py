#!/usr/bin/env python3
"""
清仓后买回 / 仍持仓风控雷达

目标：
1) 对已清仓股票判断 NO_REBUY / WATCH_REBUY / PROBE_REBUY / CONFIRMED_REBUY。
2) 对仍持仓股票判断 HOLD_OK / HOLD_WATCH / REDUCE_OR_EXIT / ADD_WATCH。
3) 优先使用 Tushare；Tushare 无数据时使用本地 akshare_stock_upgrade_output.json 缓存。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import tushare as ts
import tushare.pro.client as client

from config.runtime import REPORT_DIR, setup_logger
from config.secrets import TUSHARE_TOKEN

logger = setup_logger("rebuy_portfolio_monitor")

OUTPUT_DIR = REPORT_DIR / "Rebuy_Portfolio_Monitor"
CACHE_FILE = REPORT_DIR / "akshare_stock_upgrade_output.json"
SCHEMA_VERSION = "rebuy_portfolio.v1"

NAME_MAP: Dict[str, str] = {
    "002156.SZ": "通富微电",
    "000977.SZ": "浪潮信息",
    "002077.SZ": "大港股份",
    "601138.SH": "工业富联",
    "000938.SZ": "紫光股份",
    "000988.SZ": "华工科技",
}

CLOSED_POSITIONS: List[Dict[str, Any]] = [
    {
        "ts_code": "002156.SZ",
        "entry_price": 70.80,
        "exit_price": 63.580,
        "exit_date": "20260608",
        "original_qty": 100,
        "max_rebuy_qty": 100,
        "want_rebuy": True,
    },
    {
        "ts_code": "000977.SZ",
        "entry_price": 62.970,
        "exit_price": 58.020,
        "exit_date": "20260608",
        "original_qty": 100,
        "max_rebuy_qty": 100,
        "want_rebuy": True,
    },
    {
        "ts_code": "002077.SZ",
        "entry_price": 16.760,
        "exit_price": 15.480,
        "exit_date": "20260608",
        "original_qty": 500,
        "max_rebuy_qty": 500,
        "want_rebuy": True,
    },
]

OPEN_POSITIONS: List[Dict[str, Any]] = [
    {
        "ts_code": "601138.SH",
        "entry_price": 80.00,
        "qty": 100,
        "plan": "减仓或清仓；价格已低于 73.65，因未及时设置条件单",
        "hard_exit_price": 73.65,
    },
    {
        "ts_code": "000938.SZ",
        "entry_price": 27.540,
        "qty": 300,
        "plan": "继续持有 / 等待加仓",
        "hard_exit_price": None,
    },
    {
        "ts_code": "000988.SZ",
        "entry_price": 151.940,
        "qty": 100,
        "plan": "继续持有 / 等待加仓",
        "hard_exit_price": None,
    },
]


@dataclass
class RebuySignal:
    ts_code: str
    name: str
    trade_date: str
    signal: str
    action: str
    close: float
    entry_price: float
    exit_price: float
    max_rebuy_qty: int
    suggested_qty: int
    pnl_from_entry_pct: float
    distance_to_exit_price_pct: float
    dry_volume_ratio: float
    ma5: float
    ma10: float
    ma20: float
    black_swan_high: Optional[float]
    black_swan_low: Optional[float]
    trigger_price: float
    stop_price: float
    notes: List[str]


@dataclass
class HoldingSignal:
    ts_code: str
    name: str
    trade_date: str
    signal: str
    action: str
    close: float
    entry_price: float
    qty: int
    market_value: float
    unrealized_pnl_pct: float
    dry_volume_ratio: float
    ma5: float
    ma10: float
    ma20: float
    hard_exit_price: Optional[float]
    risk_line: float
    add_trigger_price: float
    notes: List[str]


def init_client():
    if not TUSHARE_TOKEN or "YOUR_" in TUSHARE_TOKEN:
        raise RuntimeError("请先在 config/secrets.py 配置 TUSHARE_TOKEN")
    client.DataApi._DataApi__http_url = "http://api.quicksync.cn"
    return ts.pro_api(TUSHARE_TOKEN)


def normalize_code(code: str) -> str:
    code = code.strip().upper()
    if "." in code:
        return code
    if code.startswith(("0", "2", "3")):
        return f"{code}.SZ"
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    return code


def format_trade_date(trade_date: str) -> str:
    return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}" if len(trade_date) == 8 else trade_date


def clean_daily_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.sort_values("trade_date").reset_index(drop=True).copy()
    numeric_cols = ["open", "high", "low", "close", "pre_close", "vol", "amount"]
    for col in numeric_cols:
        if col in out.columns:
            out.loc[:, col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["open", "high", "low", "close", "vol"])


def fetch_daily(pro: Any, ts_code: str, end_date: str, calendar_days: int = 180) -> pd.DataFrame:
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    start = (end_dt - timedelta(days=calendar_days)).strftime("%Y%m%d")
    fields = "ts_code,trade_date,open,high,low,close,pre_close,vol,amount"
    return clean_daily_frame(pro.daily(ts_code=ts_code, start_date=start, end_date=end_date, fields=fields))


def normalize_rt_min_frame(df: pd.DataFrame, fallback_code: Optional[str] = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    rename_map = {
        "datetime": "time",
        "date_time": "time",
        "trade_time": "time",
        "trade_date": "time",
        "code": "ts_code",
        "symbol": "ts_code",
        "volume": "vol",
    }
    out = out.rename(columns={k: v for k, v in rename_map.items() if k in out.columns and v not in out.columns})
    if "ts_code" not in out.columns and fallback_code:
        out.loc[:, "ts_code"] = fallback_code
    required = {"time", "ts_code", "open", "high", "low", "close"}
    if not required.issubset(set(out.columns)):
        logger.warning("rt_min 返回字段不足，无法合成日线。columns=%s", list(out.columns))
        return pd.DataFrame()
    out.loc[:, "ts_code"] = out["ts_code"].astype(str).map(normalize_code)
    out.loc[:, "_time"] = pd.to_datetime(out["time"], errors="coerce")
    out = out.dropna(subset=["_time"])
    for col in ["open", "high", "low", "close", "vol", "amount"]:
        if col in out.columns:
            out.loc[:, col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["open", "high", "low", "close"])


def build_daily_bars_from_rt_min(rt_df: pd.DataFrame, requested_date: str) -> Dict[str, pd.DataFrame]:
    out = normalize_rt_min_frame(rt_df)
    if out.empty:
        return {}
    out = out[out["_time"].dt.strftime("%Y%m%d") == requested_date]
    if out.empty:
        return {}

    bars: Dict[str, pd.DataFrame] = {}
    for ts_code, group in out.sort_values("_time").groupby("ts_code"):
        first = group.iloc[0]
        last = group.iloc[-1]
        vol = float(group["vol"].sum()) if "vol" in group.columns else 0.0
        amount = float(group["amount"].sum()) if "amount" in group.columns else 0.0
        bar = pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "trade_date": requested_date,
                    "open": float(first["open"]),
                    "high": float(group["high"].max()),
                    "low": float(group["low"].min()),
                    "close": float(last["close"]),
                    "pre_close": None,
                    "vol": vol,
                    "amount": amount,
                }
            ]
        )
        bars[ts_code] = clean_daily_frame(bar)
    return bars


def fetch_rt_min_bars(pro: Any, codes: List[str], requested_date: str) -> Dict[str, pd.DataFrame]:
    """Fetch rt_min in batch first, then fall back to per-symbol calls."""
    normalized = [normalize_code(code) for code in codes]
    joined = ",".join(normalized)
    attempts: List[pd.DataFrame] = []

    for kwargs in ({"ts_code": joined, "freq": "1MIN"}, {"ts_code": joined}):
        try:
            df = pro.rt_min(**kwargs)
            if df is not None and not df.empty:
                logger.info("rt_min 批量返回 %s 行，参数=%s", len(df), kwargs)
                attempts.append(df)
                break
        except Exception as exc:
            logger.warning("rt_min 批量请求失败 %s: %s", kwargs, exc)

    if attempts:
        bars = build_daily_bars_from_rt_min(attempts[0], requested_date)
        if bars:
            return bars

    bars: Dict[str, pd.DataFrame] = {}
    for code in normalized:
        for kwargs in ({"ts_code": code, "freq": "1MIN"}, {"ts_code": code}):
            try:
                df = pro.rt_min(**kwargs)
            except Exception as exc:
                logger.warning("rt_min 单票请求失败 %s %s: %s", code, kwargs, exc)
                continue
            normalized_df = normalize_rt_min_frame(df, fallback_code=code)
            one_bars = build_daily_bars_from_rt_min(normalized_df, requested_date)
            if code in one_bars and not one_bars[code].empty:
                bars[code] = one_bars[code]
                break
    return bars


def load_local_cache_frames(codes: List[str], requested_date: str) -> Dict[str, pd.DataFrame]:
    if not CACHE_FILE.exists():
        return {}
    payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    code_set = {normalize_code(code) for code in codes}
    requested_dt = datetime.strptime(requested_date, "%Y%m%d")
    frames: Dict[str, pd.DataFrame] = {}

    for stock in payload.get("stocks", []):
        kline = stock.get("daily_kline_3m") or []
        if not kline:
            continue
        ts_code = normalize_code(str(kline[0].get("ts_code") or stock.get("code") or ""))
        if ts_code not in code_set:
            continue
        rows: List[Dict[str, Any]] = []
        for item in kline:
            raw_date = str(item.get("date", ""))[:10].replace("-", "")
            if not raw_date or datetime.strptime(raw_date, "%Y%m%d") > requested_dt:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": raw_date,
                    "open": item.get("open"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "close": item.get("close"),
                    "pre_close": item.get("pre_close"),
                    "vol": item.get("volume"),
                    "amount": item.get("amount"),
                }
            )
        frame = clean_daily_frame(pd.DataFrame(rows))
        if not frame.empty:
            frames[ts_code] = frame
    return frames


def find_latest_tushare_trade_date(pro: Any, probe_code: str, requested_date: str, lookback_days: int) -> Optional[str]:
    requested_dt = datetime.strptime(requested_date, "%Y%m%d")
    for offset in range(lookback_days + 1):
        candidate = (requested_dt - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df = fetch_daily(pro, probe_code, candidate)
        except Exception as exc:
            logger.warning("Tushare 探测失败 %s %s: %s", probe_code, candidate, exc)
            continue
        if not df.empty:
            eligible = df[df["trade_date"].astype(str) <= candidate]
            if not eligible.empty:
                return str(eligible.iloc[-1]["trade_date"])
    return None


def merge_realtime_bars(
    history_frames: Dict[str, pd.DataFrame],
    realtime_frames: Dict[str, pd.DataFrame],
    requested_date: str,
) -> Dict[str, pd.DataFrame]:
    merged: Dict[str, pd.DataFrame] = {}
    for code, hist in history_frames.items():
        rt = realtime_frames.get(code, pd.DataFrame())
        if hist.empty and rt.empty:
            merged[code] = pd.DataFrame()
            continue
        base = hist[hist["trade_date"].astype(str) < requested_date].copy() if not hist.empty else pd.DataFrame()
        if not rt.empty:
            merged[code] = clean_daily_frame(pd.concat([base, rt], ignore_index=True))
        else:
            merged[code] = clean_daily_frame(base)
    return merged


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.loc[:, "ma5"] = out["close"].rolling(5, min_periods=5).mean()
    out.loc[:, "ma10"] = out["close"].rolling(10, min_periods=10).mean()
    out.loc[:, "ma20"] = out["close"].rolling(20, min_periods=20).mean()
    out.loc[:, "ma20_volume"] = out["vol"].rolling(20, min_periods=20).mean()
    out.loc[:, "dry_volume_ratio"] = out["vol"] / out["ma20_volume"]
    prev_close = out["close"].shift(1)
    tr_parts = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    out.loc[:, "true_range"] = tr_parts.max(axis=1)
    out.loc[:, "atr5"] = out["true_range"].rolling(5, min_periods=5).mean()
    out.loc[:, "body_ratio"] = (out["close"] - out["open"]).abs() / (out["high"] - out["low"]).replace(0, pd.NA)
    return out


def get_black_swan_bar(df: pd.DataFrame, exit_date: str) -> Optional[pd.Series]:
    matched = df[df["trade_date"].astype(str) == exit_date]
    if matched.empty:
        return None
    return matched.iloc[-1]


def classify_rebuy(position: Dict[str, Any], raw_df: pd.DataFrame) -> RebuySignal:
    ts_code = normalize_code(position["ts_code"])
    name = NAME_MAP.get(ts_code, ts_code)
    df = add_indicators(raw_df).tail(60).reset_index(drop=True)
    if len(df) < 25:
        raise ValueError(f"{ts_code} 可用日线不足 25 根")

    today = df.iloc[-1]
    latest_trade_date = str(today["trade_date"])
    exit_date = str(position["exit_date"])
    if latest_trade_date < exit_date:
        close = float(today["close"])
        entry_price = float(position["entry_price"])
        exit_price = float(position["exit_price"])
        max_qty = int(position["max_rebuy_qty"])
        return RebuySignal(
            ts_code=ts_code,
            name=name,
            trade_date=latest_trade_date,
            signal="DATA_STALE",
            action="数据早于清仓日，禁止生成买回信号",
            close=round(close, 2),
            entry_price=round(entry_price, 3),
            exit_price=round(exit_price, 3),
            max_rebuy_qty=max_qty,
            suggested_qty=0,
            pnl_from_entry_pct=round((close - entry_price) / entry_price, 4),
            distance_to_exit_price_pct=round((close - exit_price) / exit_price, 4),
            dry_volume_ratio=round(float(today.get("dry_volume_ratio", 0) or 0), 3),
            ma5=round(float(today.get("ma5", 0) or 0), 2),
            ma10=round(float(today.get("ma10", 0) or 0), 2),
            ma20=round(float(today.get("ma20", 0) or 0), 2),
            black_swan_high=None,
            black_swan_low=None,
            trigger_price=round(exit_price, 2),
            stop_price=round(exit_price * 0.97, 2),
            notes=[
                f"最新可用 K 线日期 {format_trade_date(latest_trade_date)} 早于你的清仓日 {format_trade_date(exit_date)}",
                "不能用清仓前的数据判断清仓后的买回时点",
                "需要等待 2026-06-08 或之后的收盘数据同步",
            ],
        )

    recent_5 = df.tail(5)
    recent_10 = df.tail(10)
    pivot_window = df.iloc[-16:-1] if len(df) >= 16 else df.iloc[:-1]
    black_bar = get_black_swan_bar(df, str(position["exit_date"]))

    close = float(today["close"])
    high = float(today["high"])
    low = float(today["low"])
    ma5 = float(today["ma5"])
    ma10 = float(today["ma10"])
    ma20 = float(today["ma20"])
    dry_ratio = float(today["dry_volume_ratio"])
    atr5 = float(today["atr5"])
    entry_price = float(position["entry_price"])
    exit_price = float(position["exit_price"])
    max_qty = int(position["max_rebuy_qty"])
    black_high = float(black_bar["high"]) if black_bar is not None else None
    black_low = float(black_bar["low"]) if black_bar is not None else None
    pivot = float(max(pivot_window["high"].max(), exit_price, black_high or exit_price))

    no_new_low = low > float(recent_5["low"].min()) or close > float(recent_5["close"].min())
    reclaim_exit = close >= exit_price
    reclaim_ma5 = close >= ma5
    reclaim_ma10 = close >= ma10
    reclaim_ma20 = close >= ma20
    quieting = dry_ratio <= 0.75 or float(today["body_ratio"] or 1) <= 0.35
    confirmed_breakout = (close > pivot or high > pivot) and dry_ratio >= 1.3 and close >= ma20
    probe_rebuy = reclaim_exit and reclaim_ma5 and no_new_low and dry_ratio <= 1.3
    watch_rebuy = no_new_low and quieting and close >= (black_low or close) * 0.98
    knife_fall = close < exit_price and dry_ratio > 1.0 and close < ma5

    notes: List[str] = []
    signal = "NO_REBUY"
    action = "禁止买回，继续等右侧确认"
    suggested_qty = 0
    trigger_price = max(exit_price, ma5)
    stop_price = round(min(low, exit_price * 0.97), 2)

    if confirmed_breakout:
        signal = "CONFIRMED_REBUY"
        action = "确认买回，可恢复计划仓位，但必须带止损"
        suggested_qty = max_qty
        trigger_price = pivot
        stop_price = round(max(exit_price * 0.97, close - 1.5 * atr5), 2)
        notes.append(f"突破关键枢纽 {pivot:.2f} 且放量，属于右侧确认")
    elif probe_rebuy:
        signal = "PROBE_REBUY"
        action = "可小仓试错买回，优先 1/3 仓"
        suggested_qty = max(1, max_qty // 3)
        trigger_price = max(exit_price, ma5)
        stop_price = round(min(exit_price * 0.98, float(recent_5["low"].min())), 2)
        notes.append("已重新站回清仓价和 MA5，且未继续放量下跌")
    elif watch_rebuy:
        signal = "WATCH_REBUY"
        action = "观察买回，等待重新站回清仓价/MA5"
        suggested_qty = 0
        trigger_price = round(max(exit_price, ma5), 2)
        stop_price = round(float(recent_5["low"].min()), 2)
        notes.append("杀跌动能有收敛迹象，但尚未给出买回触发")
    elif knife_fall:
        notes.append("仍低于清仓价和 MA5，且成交量不低，不能接飞刀")
    else:
        notes.append("尚未满足买回条件，至少等待站回清仓价或 MA5")

    if close < exit_price:
        notes.append(f"现价仍低于清仓价 {exit_price:.2f}")
    if close < entry_price:
        notes.append(f"现价仍低于原买入均价 {entry_price:.2f}")
    if black_high is not None:
        notes.append(f"黑天鹅日高低点：{black_high:.2f}/{black_low:.2f}")

    return RebuySignal(
        ts_code=ts_code,
        name=name,
        trade_date=str(today["trade_date"]),
        signal=signal,
        action=action,
        close=round(close, 2),
        entry_price=round(entry_price, 3),
        exit_price=round(exit_price, 3),
        max_rebuy_qty=max_qty,
        suggested_qty=suggested_qty,
        pnl_from_entry_pct=round((close - entry_price) / entry_price, 4),
        distance_to_exit_price_pct=round((close - exit_price) / exit_price, 4),
        dry_volume_ratio=round(dry_ratio, 3),
        ma5=round(ma5, 2),
        ma10=round(ma10, 2),
        ma20=round(ma20, 2),
        black_swan_high=round(black_high, 2) if black_high is not None else None,
        black_swan_low=round(black_low, 2) if black_low is not None else None,
        trigger_price=round(trigger_price, 2),
        stop_price=round(stop_price, 2),
        notes=notes,
    )


def classify_holding(position: Dict[str, Any], raw_df: pd.DataFrame) -> HoldingSignal:
    ts_code = normalize_code(position["ts_code"])
    name = NAME_MAP.get(ts_code, ts_code)
    df = add_indicators(raw_df).tail(60).reset_index(drop=True)
    if len(df) < 25:
        raise ValueError(f"{ts_code} 可用日线不足 25 根")

    today = df.iloc[-1]
    recent_5 = df.tail(5)
    pivot_window = df.iloc[-16:-1] if len(df) >= 16 else df.iloc[:-1]
    close = float(today["close"])
    ma5 = float(today["ma5"])
    ma10 = float(today["ma10"])
    ma20 = float(today["ma20"])
    dry_ratio = float(today["dry_volume_ratio"])
    atr5 = float(today["atr5"])
    entry_price = float(position["entry_price"])
    qty = int(position["qty"])
    hard_exit = position.get("hard_exit_price")
    hard_exit_price = float(hard_exit) if hard_exit is not None else None
    pivot = float(max(pivot_window["high"].max(), pivot_window["close"].max()))
    recent_low = float(recent_5["low"].min())
    risk_line = hard_exit_price if hard_exit_price is not None else round(max(entry_price * 0.92, recent_low - 0.3 * atr5), 2)

    notes: List[str] = []
    signal = "HOLD_WATCH"
    action = "持仓观察，暂不加仓"
    add_trigger = round(max(pivot, ma20), 2)

    if hard_exit_price is not None and close <= hard_exit_price:
        signal = "REDUCE_OR_EXIT"
        action = "已跌破预设硬风控线，优先减仓/清仓，不做加仓"
        notes.append(f"现价 {close:.2f} 已低于硬风控线 {hard_exit_price:.2f}")
    elif close < risk_line and dry_ratio > 1.0:
        signal = "REDUCE_OR_EXIT"
        action = "跌破风险线且成交量不低，优先降低风险"
        notes.append(f"跌破风险线 {risk_line:.2f}，且缩量比 {dry_ratio:.2f} 不低")
    elif close >= entry_price and close >= ma10 and dry_ratio <= 1.2:
        signal = "HOLD_OK"
        action = "可继续持有，但不追高加仓"
        notes.append("现价高于成本并站上 MA10，持仓结构暂可接受")
    elif close > add_trigger and dry_ratio >= 1.3:
        signal = "ADD_WATCH"
        action = "出现右侧加仓观察信号，等待收盘确认"
        notes.append(f"若有效突破 {add_trigger:.2f} 且放量，可考虑加仓")
    else:
        notes.append("结构尚未转强，等待站回均线或突破枢纽")

    if close < entry_price:
        notes.append(f"浮亏中：现价低于成本 {entry_price:.2f}")
    if close < ma20:
        notes.append(f"现价低于 MA20 {ma20:.2f}")

    return HoldingSignal(
        ts_code=ts_code,
        name=name,
        trade_date=str(today["trade_date"]),
        signal=signal,
        action=action,
        close=round(close, 2),
        entry_price=round(entry_price, 3),
        qty=qty,
        market_value=round(close * qty, 2),
        unrealized_pnl_pct=round((close - entry_price) / entry_price, 4),
        dry_volume_ratio=round(dry_ratio, 3),
        ma5=round(ma5, 2),
        ma10=round(ma10, 2),
        ma20=round(ma20, 2),
        hard_exit_price=hard_exit_price,
        risk_line=round(risk_line, 2),
        add_trigger_price=round(add_trigger, 2),
        notes=notes,
    )


def bullet_or_empty(items: List[str], empty_text: str) -> str:
    return "\n".join(items) if items else f"* {empty_text}"


def render_markdown(
    rebuy_signals: List[RebuySignal],
    holding_signals: List[HoldingSignal],
    as_of: str,
    requested_as_of: str,
    data_source: str,
    fallback_note: Optional[str],
    errors: List[str],
) -> str:
    confirmed: List[str] = []
    probe: List[str] = []
    watch: List[str] = []
    no_rebuy: List[str] = []
    stale_items: List[str] = []
    exit_items: List[str] = []
    hold_items: List[str] = []
    add_items: List[str] = []

    for r in rebuy_signals:
        label = f"{r.name}/{r.ts_code.split('.')[0]}"
        text = (
            f"* **[{label}]** 现价 {r.close:.2f}，清仓价 {r.exit_price:.2f}，成本 {r.entry_price:.2f}，"
            f"缩量比 {r.dry_volume_ratio:.2f}，MA5/10/20={r.ma5:.2f}/{r.ma10:.2f}/{r.ma20:.2f}\n"
            f"  * **动作**：{r.action}\n"
            f"  * **触发价**：{r.trigger_price:.2f}；**防线**：{r.stop_price:.2f}；建议买回数量：{r.suggested_qty}/{r.max_rebuy_qty}\n"
            f"  * **原因**：{'；'.join(r.notes)}"
        )
        if r.signal == "CONFIRMED_REBUY":
            confirmed.append(text)
        elif r.signal == "PROBE_REBUY":
            probe.append(text)
        elif r.signal == "WATCH_REBUY":
            watch.append(text)
        elif r.signal == "DATA_STALE":
            stale_items.append(text)
        else:
            no_rebuy.append(text)

    for h in holding_signals:
        label = f"{h.name}/{h.ts_code.split('.')[0]}"
        text = (
            f"* **[{label}]** 现价 {h.close:.2f}，成本 {h.entry_price:.2f}，数量 {h.qty}，"
            f"浮盈亏 {h.unrealized_pnl_pct:.2%}，缩量比 {h.dry_volume_ratio:.2f}\n"
            f"  * **动作**：{h.action}\n"
            f"  * **风险线**：{h.risk_line:.2f}；**加仓触发价**：{h.add_trigger_price:.2f}\n"
            f"  * **原因**：{'；'.join(h.notes)}"
        )
        if h.signal == "REDUCE_OR_EXIT":
            exit_items.append(text)
        elif h.signal == "ADD_WATCH":
            add_items.append(text)
        else:
            hold_items.append(text)

    fallback_block = f"#### 🕒 【DATA 回退说明】\n* {fallback_note}\n\n" if fallback_note else ""
    error_block = ""
    if errors:
        error_block = "\n\n#### ⚙️ 【DATA 数据异常区】\n" + "\n".join(f"* {err}" for err in errors)

    return (
        f"### 🦅 清仓后买回 / 持仓风控雷达 (As of: {as_of})\n"
        f"> 请求日期：{requested_as_of}；实际使用数据日期：{as_of}；数据来源：{data_source}\n\n"
        f"{fallback_block}"
        "#### ✅ 【CONFIRMED_REBUY 确认买回区】\n"
        f"{bullet_or_empty(confirmed, '暂无确认买回信号。')}\n\n"
        "#### 🟡 【PROBE_REBUY 小仓试错区】\n"
        f"{bullet_or_empty(probe, '暂无小仓试错买回信号。')}\n\n"
        "#### 🔍 【WATCH_REBUY 观察买回区】\n"
        f"{bullet_or_empty(watch, '暂无进入观察买回区的清仓票。')}\n\n"
        "#### ⛔ 【NO_REBUY 禁止买回区】\n"
        f"{bullet_or_empty(no_rebuy, '暂无禁止买回票。')}\n\n"
        "#### ⚙️ 【DATA_STALE 数据过旧禁判区】\n"
        f"{bullet_or_empty(stale_items, '暂无因数据过旧而禁止判断的清仓票。')}\n\n"
        "#### 🔴 【REDUCE_OR_EXIT 持仓减仓/清仓区】\n"
        f"{bullet_or_empty(exit_items, '暂无触发减仓/清仓风控的持仓票。')}\n\n"
        "#### 🟢 【HOLD / ADD_WATCH 持仓管理区】\n"
        f"{bullet_or_empty(hold_items + add_items, '暂无持仓管理项。')}"
        f"{error_block}\n\n"
        "---\n"
        "纪律：黑天鹅后不猜底；只在止跌、缩量、重新站回关键价后分批买回。"
    )


def run_monitor(requested_date: str, lookback_days: int = 30) -> Dict[str, Any]:
    all_codes = [p["ts_code"] for p in CLOSED_POSITIONS + OPEN_POSITIONS]
    normalized_codes = [normalize_code(code) for code in all_codes]
    pro = init_client()
    probe_code = normalized_codes[0]
    actual_trade_date = find_latest_tushare_trade_date(pro, probe_code, requested_date, lookback_days)
    data_source = "tushare"
    frames: Dict[str, pd.DataFrame] = {}

    if actual_trade_date:
        for code in normalized_codes:
            frames[code] = fetch_daily(pro, code, actual_trade_date)
    else:
        history_frames = load_local_cache_frames(normalized_codes, requested_date)
        realtime_frames = fetch_rt_min_bars(pro, normalized_codes, requested_date)
        if realtime_frames and history_frames:
            frames = merge_realtime_bars(history_frames, realtime_frames, requested_date)
            actual_trade_date = requested_date
            data_source = f"local_cache:{CACHE_FILE.name}+tushare.rt_min"
        elif history_frames:
            frames = history_frames
            actual_trade_date = max(str(frame.iloc[-1]["trade_date"]) for frame in frames.values())
            data_source = f"local_cache:{CACHE_FILE.name}"
        else:
            raise RuntimeError("Tushare 日线、Tushare 实时分钟和本地缓存均未返回可用 K 线")

    fallback_note: Optional[str] = None
    if data_source.endswith("tushare.rt_min"):
        fallback_note = (
            f"请求日期 {format_trade_date(requested_date)} 暂无 Tushare 日线，但 rt_min 实时分钟接口已返回当日数据。"
            f"系统使用本地历史 K 线 + {format_trade_date(requested_date)} 实时分钟合成日线，"
            "因此本报告可用于 6.8 当日盘后买回/风控判断。"
        )
        logger.warning(fallback_note)
    elif actual_trade_date != requested_date or data_source != "tushare":
        fallback_note = (
            f"请求日期 {format_trade_date(requested_date)} 暂无 Tushare 有效日线，"
            f"系统使用 {data_source} 中最近可用交易日 {format_trade_date(actual_trade_date)}。"
            "因此本报告是最近可用数据的买回计划，不代表 6.8 实时收盘结果。"
        )
        logger.warning(fallback_note)

    rebuy_signals: List[RebuySignal] = []
    holding_signals: List[HoldingSignal] = []
    errors: List[str] = []

    for position in CLOSED_POSITIONS:
        ts_code = normalize_code(position["ts_code"])
        try:
            rebuy_signals.append(classify_rebuy(position, frames.get(ts_code, pd.DataFrame())))
        except Exception as exc:
            logger.exception("买回信号失败: %s", ts_code)
            errors.append(f"{NAME_MAP.get(ts_code, ts_code)}/{ts_code}: {exc}")

    for position in OPEN_POSITIONS:
        ts_code = normalize_code(position["ts_code"])
        try:
            holding_signals.append(classify_holding(position, frames.get(ts_code, pd.DataFrame())))
        except Exception as exc:
            logger.exception("持仓信号失败: %s", ts_code)
            errors.append(f"{NAME_MAP.get(ts_code, ts_code)}/{ts_code}: {exc}")

    as_of = max(
        [s.trade_date for s in rebuy_signals] + [s.trade_date for s in holding_signals],
        default=actual_trade_date,
    )
    as_of_fmt = format_trade_date(as_of)
    requested_fmt = format_trade_date(requested_date)
    markdown = render_markdown(rebuy_signals, holding_signals, as_of_fmt, requested_fmt, data_source, fallback_note, errors)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUTPUT_DIR / f"rebuy_portfolio_report_{as_of}.md"
    json_path = OUTPUT_DIR / f"rebuy_portfolio_report_{as_of}.json"
    latest_md = OUTPUT_DIR / "latest.md"
    latest_json = OUTPUT_DIR / "latest.json"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "requested_as_of": requested_fmt,
        "as_of": as_of_fmt,
        "actual_trade_date": as_of,
        "data_source": data_source,
        "fallback_note": fallback_note,
        "closed_positions": CLOSED_POSITIONS,
        "open_positions": OPEN_POSITIONS,
        "rebuy_signals": [asdict(item) for item in rebuy_signals],
        "holding_signals": [asdict(item) for item in holding_signals],
        "errors": errors,
        "report_path": str(md_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(markdown)
    print(f"\n\n[REPORT] Markdown: {md_path}")
    print(f"[REPORT] JSON: {json_path}")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="清仓后买回 / 持仓风控雷达")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"), help="请求分析日期，格式 YYYYMMDD")
    parser.add_argument("--lookback-days", type=int, default=30, help="Tushare 无数据时向前探测天数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_monitor(args.date, args.lookback_days)


if __name__ == "__main__":
    main()
