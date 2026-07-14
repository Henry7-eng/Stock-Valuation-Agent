#!/usr/bin/env python3
"""
影子审计切片脚本（time_slice_tester）

功能：
1) 输入 stock_code + end_date(YYYYMMDD)
2) 严格只拉取 end_date 及以前数据，提取最近 150 个交易日日线
3) 计算 30-WMA 与斜率（基于最近 10 个交易日的线性回归斜率）
4) 计算过去 12 周（约 60 交易日）的 VCP 波动收缩特征
5) 以 Markdown 表格输出，并附盲审指令
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
import pandas as pd
import tushare as ts
import tushare.pro.client as client

from config.secrets import TUSHARE_TOKEN


@dataclass
class SliceMetrics:
    ts_code: str
    end_date: str
    bars_count: int
    close_price: float
    ma30_wma: float
    ma30_wma_slope: float
    vcp_range_ratio: float
    vcp_vol_ratio: float
    vcp_highs_descending: bool
    vcp_lows_ascending: bool
    vcp_score: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="影子审计历史切片测试器")
    parser.add_argument("stock_code", type=str, help="股票代码，如 000001.SZ")
    parser.add_argument("end_date", type=str, help="审计截止日，格式 YYYYMMDD")
    return parser.parse_args()


def validate_date_str(end_date: str) -> None:
    if len(end_date) != 8 or not end_date.isdigit():
        raise ValueError("end_date 必须是 YYYYMMDD 格式，例如 20250531")


def init_tushare() -> ts.pro_api:
    if not TUSHARE_TOKEN or "YOUR_" in TUSHARE_TOKEN:
        raise RuntimeError("请先在 config/secrets.py 中配置真实 TUSHARE_TOKEN")
    client.DataApi._DataApi__http_url = "http://api.quicksync.cn"
    return ts.pro_api(TUSHARE_TOKEN)


def fetch_150_trade_days(pro, stock_code: str, end_date: str) -> pd.DataFrame:
    # 这里用更长窗口拉取，然后在本地截断到 <= end_date 的最后150个交易日
    # 目的是稳妥覆盖停牌/节假日等情况，但仍然严格禁止使用 end_date 之后数据。
    raw = pro.daily(ts_code=stock_code, end_date=end_date, limit=400)
    if raw is None or raw.empty:
        raise RuntimeError(f"未获取到 {stock_code} 在 {end_date} 之前的日线数据")

    df = raw.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    df = df[df["trade_date"] <= end_date]

    if df.empty:
        raise RuntimeError(f"过滤后无可用数据：{stock_code} <= {end_date}")

    # Tushare daily 通常为倒序，统一转正序
    df = df.sort_values("trade_date").reset_index(drop=True)

    if len(df) < 150:
        raise RuntimeError(f"可用交易日不足 150 天，当前仅 {len(df)} 天")

    return df.iloc[-150:].reset_index(drop=True)


def weighted_ma(series: pd.Series, period: int = 30) -> pd.Series:
    weights = np.arange(1, period + 1, dtype=float)

    def _wma(x: np.ndarray) -> float:
        return float(np.dot(x, weights) / weights.sum())

    return series.rolling(period).apply(_wma, raw=True)


def linear_slope_last_n(series: pd.Series, n: int = 10) -> float:
    sub = series.dropna().iloc[-n:]
    if len(sub) < n:
        return float("nan")
    y = sub.values.astype(float)
    x = np.arange(len(y), dtype=float)
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def compute_vcp_features(df_150: pd.DataFrame) -> Tuple[float, float, bool, bool, int]:
    # 过去12周近似为 60 个交易日
    df_60 = df_150.iloc[-60:].copy()

    # 将 60 个交易日拆成 4 个 15 日窗口，观察波动/量能是否逐步收缩
    windows = []
    for i in range(4):
        seg = df_60.iloc[i * 15 : (i + 1) * 15]
        if seg.empty:
            continue
        high = float(seg["high"].max())
        low = float(seg["low"].min())
        mean_close = float(seg["close"].mean()) if float(seg["close"].mean()) != 0 else 1e-9
        price_range = (high - low) / mean_close
        vol_mean = float(seg["vol"].mean())
        windows.append((price_range, vol_mean, high, low))

    if len(windows) < 4:
        return float("nan"), float("nan"), False, False, 0

    ranges = [w[0] for w in windows]
    vols = [w[1] for w in windows]
    highs = [w[2] for w in windows]
    lows = [w[3] for w in windows]

    # 核心收缩比：最后窗口 / 第一个窗口（越小越收缩）
    vcp_range_ratio = ranges[-1] / ranges[0] if ranges[0] != 0 else float("inf")
    vcp_vol_ratio = vols[-1] / vols[0] if vols[0] != 0 else float("inf")

    highs_descending = highs[0] > highs[1] > highs[2] > highs[3]
    lows_ascending = lows[0] < lows[1] < lows[2] < lows[3]

    score = 0
    if vcp_range_ratio < 0.8:
        score += 1
    if vcp_vol_ratio < 0.8:
        score += 1
    if highs_descending:
        score += 1
    if lows_ascending:
        score += 1

    return float(vcp_range_ratio), float(vcp_vol_ratio), highs_descending, lows_ascending, score


def build_metrics(stock_code: str, end_date: str) -> SliceMetrics:
    pro = init_tushare()
    df_150 = fetch_150_trade_days(pro, stock_code, end_date)

    df_150["wma30"] = weighted_ma(df_150["close"], period=30)
    wma_slope = linear_slope_last_n(df_150["wma30"], n=10)

    vcp_range_ratio, vcp_vol_ratio, highs_desc, lows_asc, vcp_score = compute_vcp_features(df_150)

    return SliceMetrics(
        ts_code=stock_code,
        end_date=end_date,
        bars_count=len(df_150),
        close_price=float(df_150.iloc[-1]["close"]),
        ma30_wma=float(df_150.iloc[-1]["wma30"]),
        ma30_wma_slope=float(wma_slope),
        vcp_range_ratio=float(vcp_range_ratio),
        vcp_vol_ratio=float(vcp_vol_ratio),
        vcp_highs_descending=bool(highs_desc),
        vcp_lows_ascending=bool(lows_asc),
        vcp_score=int(vcp_score),
    )


def to_markdown_table(m: SliceMetrics) -> str:
    bool_zh = lambda x: "是" if x else "否"

    rows: Dict[str, str] = {
        "股票代码": m.ts_code,
        "审计截止日": m.end_date,
        "样本交易日数": str(m.bars_count),
        "截止日收盘价": f"{m.close_price:.3f}",
        "30-WMA": f"{m.ma30_wma:.3f}",
        "30-WMA 斜率(近10日)": f"{m.ma30_wma_slope:.6f}",
        "VCP 波动收缩比(末窗/首窗)": f"{m.vcp_range_ratio:.4f}",
        "VCP 量能收缩比(末窗/首窗)": f"{m.vcp_vol_ratio:.4f}",
        "VCP 高点递减": bool_zh(m.vcp_highs_descending),
        "VCP 低点抬升": bool_zh(m.vcp_lows_ascending),
        "VCP 综合评分(0-4)": str(m.vcp_score),
    }

    lines = [
        "| 指标 | 数值 |",
        "|---|---:|",
    ]
    for k, v in rows.items():
        lines.append(f"| {k} | {v} |")

    lines.append("")
    lines.append("指令：请根据《2.0 战术执行手册》对以上历史切片数据进行盲审。")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    validate_date_str(args.end_date)

    metrics = build_metrics(args.stock_code.strip().upper(), args.end_date.strip())
    print(to_markdown_table(metrics))


if __name__ == "__main__":
    main()
