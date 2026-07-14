#!/usr/bin/env python3
"""
猎手每日缩量监控雷达（Tushare）

对指定观察池标的进行 VCP 波动率收缩、极限缩量、右侧带量突破与假突破监控。
输出 Markdown 战报与机器可读 JSON。
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

logger = setup_logger("vcp_dry_volume_monitor")

WATCHLIST: Dict[str, str] = {
    "000938.SZ": "紫光股份",
    "000977.SZ": "浪潮信息",
    "000988.SZ": "华工科技",
    "002077.SZ": "大港股份",
    "002156.SZ": "通富微电",
    "601138.SH": "工业富联",
}

SCHEMA_VERSION = "vcp_dry_volume.v1"
OUTPUT_DIR = REPORT_DIR / "VCP_Dry_Volume_Monitor"
STATE_FILE = OUTPUT_DIR / "breakout_state.json"
CACHE_FILE = REPORT_DIR / "akshare_stock_upgrade_output.json"


@dataclass
class MonitorResult:
    ts_code: str
    name: str
    trade_date: str
    state: str
    action: str
    close: float
    high: float
    low: float
    volume: float
    ma20_volume: float
    dry_volume_ratio: float
    ma20_price: float
    bias_ma20: float
    atr_5: float
    atr_5_pct: float
    atr_contraction_ratio: float
    pivot_point: float
    support_floor: float
    range_days: int
    body_ratio: float
    stop_loss_5pct: Optional[float]
    stop_loss_8pct: Optional[float]
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
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["open", "high", "low", "close", "vol"])


def fetch_daily(pro: Any, ts_code: str, end_date: str, calendar_days: int = 180) -> pd.DataFrame:
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    start = (end_dt - timedelta(days=calendar_days)).strftime("%Y%m%d")
    fields = "ts_code,trade_date,open,high,low,close,pre_close,vol,amount"
    df = pro.daily(ts_code=ts_code, start_date=start, end_date=end_date, fields=fields)
    return clean_daily_frame(df)


def find_latest_available_trade_date(pro: Any, probe_code: str, requested_date: str, lookback_days: int) -> Optional[str]:
    """Find the newest Tushare daily bar not later than requested_date."""
    requested_dt = datetime.strptime(requested_date, "%Y%m%d")
    for offset in range(lookback_days + 1):
        candidate = (requested_dt - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df = fetch_daily(pro, probe_code, candidate)
        except Exception as exc:
            logger.warning("回退探测失败 %s %s: %s", probe_code, candidate, exc)
            continue
        if not df.empty:
            eligible = df[df["trade_date"].astype(str) <= candidate]
            if not eligible.empty:
                return str(eligible.iloc[-1]["trade_date"])
    return None


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


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ma20_volume"] = out["vol"].rolling(20, min_periods=20).mean()
    out["dry_volume_ratio"] = out["vol"] / out["ma20_volume"]
    out["ma20_price"] = out["close"].rolling(20, min_periods=20).mean()
    out["bias_ma20"] = (out["close"] - out["ma20_price"]) / out["ma20_price"]

    prev_close = out["close"].shift(1)
    tr_parts = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    out["true_range"] = tr_parts.max(axis=1)
    out["atr_5"] = out["true_range"].rolling(5, min_periods=5).mean()
    out["atr_5_pct"] = out["atr_5"] / out["close"]
    out["atr_20"] = out["true_range"].rolling(20, min_periods=20).mean()
    out["atr_contraction_ratio"] = out["atr_5"] / out["atr_20"]
    out["body_ratio"] = (out["close"] - out["open"]).abs() / (out["high"] - out["low"]).replace(0, pd.NA)
    return out


def load_breakout_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("突破状态文件读取失败，将重建: %s", STATE_FILE)
        return {}


def save_breakout_state(state: Dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_sideways_days(df: pd.DataFrame, max_days: int = 15) -> int:
    latest_close = float(df.iloc[-1]["close"])
    count = 0
    for window in range(5, min(max_days, len(df)) + 1):
        recent = df.tail(window)
        lowest = float(recent["low"].min())
        highest = float(recent["high"].max())
        if lowest <= 0:
            continue
        range_pct = (highest - lowest) / latest_close
        low_stable = latest_close >= lowest * 1.03
        if range_pct <= 0.18 and low_stable:
            count = window
    return count


def classify_stock(ts_code: str, name: str, raw_df: pd.DataFrame, state_store: Dict[str, Any]) -> MonitorResult:
    df = add_indicators(raw_df).tail(40).reset_index(drop=True)
    if len(df) < 25:
        raise ValueError(f"{ts_code} 可用日线不足 25 根，无法计算 MA20/ATR")

    today = df.iloc[-1]
    recent_15 = df.tail(15)
    prior_15 = df.iloc[-30:-15] if len(df) >= 30 else df.iloc[:-15]
    pivot_window = df.iloc[-16:-1] if len(df) >= 16 else df.iloc[:-1]
    if pivot_window.empty:
        pivot_window = df.tail(10)

    pivot_point = float(max(pivot_window["close"].max(), pivot_window["high"].max()))
    support_floor = float(recent_15["low"].min())
    range_days = detect_sideways_days(df)

    close = float(today["close"])
    high = float(today["high"])
    low = float(today["low"])
    dry_ratio = float(today["dry_volume_ratio"])
    bias_ma20 = float(today["bias_ma20"])
    atr_ratio = float(today["atr_contraction_ratio"])
    body_ratio = float(today["body_ratio"]) if pd.notna(today["body_ratio"]) else 1.0

    new_stage_low = close <= float(recent_15["close"].min()) or low <= float(recent_15["low"].min())
    prior_low = float(prior_15["low"].min()) if not prior_15.empty else support_floor
    stopped_new_low = low > prior_low * 0.98 or range_days >= 5
    small_body = body_ratio <= 0.35
    atr_contracting = atr_ratio <= 0.75 or float(today["atr_5_pct"]) <= float(df["atr_5_pct"].tail(20).quantile(0.35))
    breakout_now = (close > pivot_point or high > pivot_point) and dry_ratio > 1.5

    notes: List[str] = []
    state = "A"
    action = "IGNORE 忽略"
    stop_loss_5pct: Optional[float] = None
    stop_loss_8pct: Optional[float] = None

    existing_breakout = state_store.get(ts_code)
    failed_breakout = False
    if existing_breakout:
        breakout_date = str(existing_breakout.get("trade_date", ""))
        days_since = len(df[df["trade_date"].astype(str) > breakout_date])
        old_pivot = float(existing_breakout.get("pivot_point", pivot_point))
        if 0 < days_since <= 3 and close < old_pivot and dry_ratio > 1.0:
            failed_breakout = True
            pivot_point = old_pivot
            notes.append(f"突破后 {days_since} 个交易日内放量跌回枢纽价下方")
        elif days_since > 3 or close >= old_pivot:
            state_store.pop(ts_code, None)

    if failed_breakout:
        state = "D"
        action = "WARNING 假突破警报"
    elif breakout_now:
        state = "C"
        action = "ACTION 立即开火"
        stop_loss_5pct = round(pivot_point * 0.95, 2)
        stop_loss_8pct = round(pivot_point * 0.92, 2)
        state_store[ts_code] = {
            "trade_date": str(today["trade_date"]),
            "pivot_point": round(pivot_point, 3),
            "close": round(close, 3),
        }
        notes.append("收盘价或盘中价突破枢纽价，且缩量比 > 1.5")
    elif new_stage_low and dry_ratio > 1.0 and bias_ma20 < 0:
        state = "A"
        action = "IGNORE 忽略"
        notes.append("阶段新低/接近新低，且放量分歧，价格位于 MA20 下方")
    elif stopped_new_low and dry_ratio < 0.6 and atr_contracting and (small_body or range_days >= 5):
        state = "B"
        action = "RADAR 重点监控"
        if dry_ratio < 0.4:
            notes.append("极度干涸：缩量比 < 0.4")
        notes.append("抛压收缩，波动率下降，进入 VCP 雷达区")
    else:
        state = "A"
        action = "IGNORE 忽略"
        notes.append("尚未满足极致缩量或右侧突破确认条件")

    return MonitorResult(
        ts_code=ts_code,
        name=name,
        trade_date=str(today["trade_date"]),
        state=state,
        action=action,
        close=round(close, 2),
        high=round(high, 2),
        low=round(low, 2),
        volume=round(float(today["vol"]), 2),
        ma20_volume=round(float(today["ma20_volume"]), 2),
        dry_volume_ratio=round(dry_ratio, 3),
        ma20_price=round(float(today["ma20_price"]), 2),
        bias_ma20=round(bias_ma20, 4),
        atr_5=round(float(today["atr_5"]), 3),
        atr_5_pct=round(float(today["atr_5_pct"]), 4),
        atr_contraction_ratio=round(atr_ratio, 3),
        pivot_point=round(pivot_point, 2),
        support_floor=round(support_floor, 2),
        range_days=range_days,
        body_ratio=round(body_ratio, 3),
        stop_loss_5pct=stop_loss_5pct,
        stop_loss_8pct=stop_loss_8pct,
        notes=notes,
    )


def bullet_or_empty(items: List[str], empty_text: str) -> str:
    return "\n".join(items) if items else f"* {empty_text}"


def render_markdown(
    results: List[MonitorResult],
    as_of: str,
    requested_as_of: str,
    fallback_note: Optional[str],
    errors: List[str],
) -> str:
    action_items: List[str] = []
    radar_items: List[str] = []
    ignore_items: List[str] = []
    warning_items: List[str] = []

    fallback_block = ""
    if fallback_note:
        fallback_block = f"#### 🕒 【DATA 回退说明】\n* {fallback_note}\n\n"

    for r in results:
        label = f"{r.name}/{r.ts_code.split('.')[0]}"
        if r.state == "C":
            action_items.append(
                f"* **[{label}]**\n"
                f"  * **今日动作**：突破确认！\n"
                f"  * **数据支撑**：现价 {r.close:.2f} > 枢纽价 {r.pivot_point:.2f}，今日缩量比急升至 {r.dry_volume_ratio:.2f} (>1.5)。\n"
                f"  * **建议防线**：突破点下方 5%-8%，止损区间 {r.stop_loss_5pct:.2f} - {r.stop_loss_8pct:.2f}。"
            )
        elif r.state == "B":
            dry_label = "【极度干涸】" if r.dry_volume_ratio < 0.4 else ""
            radar_items.append(
                f"* **[{label}]**\n"
                f"  * **当前状态**：已横盘 {r.range_days} 天。\n"
                f"  * **缩量深度**：今日缩量比为 {r.dry_volume_ratio:.2f} {dry_label}(要求 <0.6)。\n"
                f"  * **目标扳机**：死盯上沿枢纽价 **{r.pivot_point:.2f}**，等待放量信号。"
            )
        elif r.state == "D":
            warning_items.append(
                f"* **[{label}]**\n"
                f"  * **今日动作**：假突破警报！\n"
                f"  * **数据支撑**：现价 {r.close:.2f} 跌回枢纽价 {r.pivot_point:.2f} 下方，缩量比 {r.dry_volume_ratio:.2f}。\n"
                f"  * **处理指令**：多头结构破坏，降级为 A/B 重新观察。"
            )
        else:
            reason = "；".join(r.notes) if r.notes else "价格仍处于无序波动"
            ignore_items.append(
                f"* **[{label}]**：缩量比 {r.dry_volume_ratio:.2f}，价格 {r.close:.2f}，MA20 偏离 {r.bias_ma20:.2%}，{reason}，忽略。"
            )

    error_block = ""
    if errors:
        error_lines = "\n".join(f"* {err}" for err in errors)
        error_block = f"\n\n#### ⚙️ 【DATA 数据异常区】\n{error_lines}\n"

    return (
        f"### 🦅 猎手每日缩量监控雷达 (As of: {as_of})\n"
        f"> 请求日期：{requested_as_of}；实际使用数据日期：{as_of}\n\n"
        f"{fallback_block}"
        "#### 🎯 【ACTION 立即开火区】(满足突破 + 放量)\n"
        f"{bullet_or_empty(action_items, '今日无满足突破 + 放量的确认买点。')}\n\n"
        "#### 🔍 【RADAR 极致缩量监控区】(抛压枯竭，随时突袭)\n"
        f"{bullet_or_empty(radar_items, '今日无进入极致缩量雷达区的标的。')}\n\n"
        "#### 🔴 【WARNING 假突破警报区】(突破后三日内跌回箱体)\n"
        f"{bullet_or_empty(warning_items, '今日无假突破回踩警报。')}\n\n"
        "#### 💤 【IGNORE 混乱洗盘区】(多空交战，继续等待)\n"
        f"{bullet_or_empty(ignore_items, '今日无混乱洗盘区标的。')}"
        f"{error_block}\n\n"
        "---\n"
        "⚠️ **系统提示**：绝不买在最低点，只买在缩量结束、资金点火的确定性拐点。"
    )


def run_monitor(codes: List[str], requested_date: Optional[str] = None, lookback_days: int = 10) -> Dict[str, Any]:
    pro = init_client()
    state_store = load_breakout_state()
    results: List[MonitorResult] = []
    errors: List[str] = []

    requested_trade_date = requested_date or datetime.now().strftime("%Y%m%d")
    normalized_codes = [normalize_code(code) for code in codes]
    probe_code = normalized_codes[0] if normalized_codes else next(iter(WATCHLIST))
    actual_trade_date = find_latest_available_trade_date(pro, probe_code, requested_trade_date, lookback_days)
    data_source = "tushare"
    cached_frames: Dict[str, pd.DataFrame] = {}

    if not actual_trade_date:
        cached_frames = load_local_cache_frames(normalized_codes, requested_trade_date)
        if cached_frames:
            actual_trade_date = max(str(frame.iloc[-1]["trade_date"]) for frame in cached_frames.values())
            data_source = "local_cache"
        else:
            raise RuntimeError(f"Tushare 在 {requested_trade_date} 往前 {lookback_days} 天内未找到可用日线数据，本地缓存也无可用 K 线")

    fallback_note: Optional[str] = None
    if actual_trade_date != requested_trade_date or data_source != "tushare":
        source_text = "Tushare" if data_source == "tushare" else f"本地缓存 {CACHE_FILE.name}"
        fallback_note = (
            f"Tushare 当前未返回请求日期 {format_trade_date(requested_trade_date)} 的有效日线数据，"
            f"系统已自动回退到最近一个可用交易日 {format_trade_date(actual_trade_date)}，"
            f"数据来源为 {source_text}。"
            "本报告所有价格、成交量、缩量比和突破判断均基于回退后的交易日数据。"
        )
        logger.warning(fallback_note)

    for ts_code in normalized_codes:
        name = WATCHLIST.get(ts_code, ts_code)
        try:
            if data_source == "local_cache":
                df = cached_frames.get(ts_code, pd.DataFrame())
            else:
                df = fetch_daily(pro, ts_code, actual_trade_date)
            if df.empty:
                raise ValueError(f"{data_source} 未返回截至 {actual_trade_date} 的日线数据")
            df = df[df["trade_date"].astype(str) <= actual_trade_date]
            if df.empty:
                raise ValueError(f"{data_source} 返回数据中缺少 {actual_trade_date} 及以前的日线")
            results.append(classify_stock(ts_code, name, df, state_store))
        except Exception as exc:
            msg = f"{name}/{ts_code}: {exc}"
            logger.exception("监控失败: %s", msg)
            errors.append(msg)

    save_breakout_state(state_store)
    as_of = max((r.trade_date for r in results), default=actual_trade_date)
    as_of_fmt = format_trade_date(as_of)
    requested_as_of_fmt = format_trade_date(requested_trade_date)
    markdown = render_markdown(results, as_of_fmt, requested_as_of_fmt, fallback_note, errors)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUTPUT_DIR / f"vcp_dry_volume_report_{as_of}.md"
    json_path = OUTPUT_DIR / f"vcp_dry_volume_report_{as_of}.json"
    latest_md_path = OUTPUT_DIR / "latest.md"
    latest_json_path = OUTPUT_DIR / "latest.json"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "requested_as_of": requested_as_of_fmt,
        "as_of": as_of_fmt,
        "actual_trade_date": as_of,
        "data_source": data_source,
        "fallback_used": actual_trade_date != requested_trade_date or data_source != "tushare",
        "fallback_note": fallback_note,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "watchlist": WATCHLIST,
        "results": [asdict(r) for r in results],
        "errors": errors,
        "report_path": str(md_path),
    }

    md_path.write_text(markdown, encoding="utf-8")
    latest_md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(markdown)
    print(f"\n\n[REPORT] Markdown: {md_path}")
    print(f"[REPORT] JSON: {json_path}")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="每日 VCP / 极限缩量 / 右侧突破监控")
    parser.add_argument(
        "--codes",
        nargs="*",
        default=list(WATCHLIST.keys()),
        help="观察池代码，支持 000938 或 000938.SZ；默认使用内置核心观察池",
    )
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y%m%d"),
        help="请求分析日期，格式 YYYYMMDD；若无数据会自动向前回退",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=10,
        help="请求日期无数据时，最多向前回退的自然日天数",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_monitor(args.codes, requested_date=args.date, lookback_days=args.lookback_days)


if __name__ == "__main__":
    main()
