#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双源稳定版 A 股跟踪脚本（akshare + tushare）

运行前：
1) 安装依赖: pip install -U akshare tushare pandas numpy requests openpyxl
2) 设置环境变量: export TUSHARE_TOKEN='你的token'
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.runtime import REPORT_DIR, setup_logger
from config.secrets import TUSHARE_TOKEN

import akshare as ak
import numpy as np
import pandas as pd
import tushare as ts
import tushare.pro.client as client

client.DataApi._DataApi__http_url = "http://api.quicksync.cn"

logger = setup_logger("akshare_stock_upgrade")

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "config" / "settings.json"
SETTINGS = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("akshare_stock_upgrade", {})
STOCKS = {str(k): str(v) for k, v in SETTINGS.get("stocks", {}).items()}
DATA_SOURCE = str(SETTINGS.get("data_source", "tushare_only")).strip().lower()
ENABLE_AK_FALLBACK = bool(SETTINGS.get("enable_akshare_fallback", False))
SCHEMA_VERSION = "stage4.v1"


def to_ts_code(code: str) -> str:
    return f"{code}.SZ" if code.startswith(("00", "30")) else f"{code}.SH"


def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        if isinstance(x, str):
            x = x.replace(",", "").replace("%", "").strip()
            if x in {"", "-", "--", "None", "nan"}:
                return None
        return float(x)
    except Exception:
        return None


def pick_first(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def with_retry(func, *args, retries: int = 4, base_sleep: float = 1.2, jitter: float = 0.4, **kwargs):
    last_err = None
    for i in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if i == retries - 1:
                break
            time.sleep(base_sleep * (2 ** i) + random.uniform(0, jitter))
    raise last_err


def get_tushare_client():
    token = (TUSHARE_TOKEN or "").strip() or os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        logger.warning("未配置 Tushare token，已切换为降级模式（仅使用 AkShare 数据）")
        return None
    try:
        os.environ["TUSHARE_TOKEN"] = token
        os.environ["CURL_CA_BUNDLE"] = ""
        os.environ["REQUESTS_CA_BUNDLE"] = ""
        os.environ.pop("TUSHARE_CACHE_DIR", None)
        os.environ.pop("TUSHARE_CACHE_FILE", None)
        os.environ.pop("TK_CSV", None)
        os.environ["HOME"] = str(Path.home())
        os.environ["TMPDIR"] = "/tmp"
        client.DataApi._DataApi__http_url = "http://api.quicksync.cn"
        ts.set_token(token)
        return ts.pro_api()
    except Exception as exc:
        logger.warning("Tushare 初始化失败，已降级为 AkShare-only：%s", exc)
        return None


def fetch_spot_snapshot() -> pd.DataFrame:
    if DATA_SOURCE == "tushare_only" and not ENABLE_AK_FALLBACK:
        return pd.DataFrame()
    try:
        return with_retry(ak.stock_zh_a_spot_em, retries=5)
    except Exception:
        return pd.DataFrame()


def fetch_daily_kline_tushare(pro, code: str, months: int = 12) -> pd.DataFrame:
    if pro is None:
        return pd.DataFrame()
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=31 * months + 30)).strftime("%Y%m%d")
    ts_code = to_ts_code(code)
    try:
        df = with_retry(
            pro.daily,
            ts_code=ts_code,
            start_date=start,
            end_date=end,
            retries=4,
        )
        if df is None or df.empty:
            return pd.DataFrame()
        out = df.rename(
            columns={
                "trade_date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "vol": "volume",
                "amount": "amount",
            }
        )
        out["date"] = pd.to_datetime(out["date"], format="%Y%m%d", errors="coerce")
        out = out.sort_values("date").reset_index(drop=True)
        return out
    except Exception:
        return pd.DataFrame()


def fetch_daily_kline_akshare(code: str, months: int = 8) -> pd.DataFrame:
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=31 * months + 30)).strftime("%Y%m%d")
    try:
        df = with_retry(
            ak.stock_zh_a_hist,
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
            retries=5,
        )
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
            }
        )
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df.sort_values("date").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def fetch_weekly_kline_tushare(pro, code: str) -> pd.DataFrame:
    if pro is None:
        return pd.DataFrame()
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=900)).strftime("%Y%m%d")
    ts_code = to_ts_code(code)
    try:
        df = with_retry(
            pro.weekly,
            ts_code=ts_code,
            start_date=start,
            end_date=end,
            retries=4,
        )
        if df is None or df.empty:
            return pd.DataFrame()
        out = df.rename(
            columns={
                "trade_date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "vol": "volume",
                "amount": "amount",
            }
        )
        out["date"] = pd.to_datetime(out["date"], format="%Y%m%d", errors="coerce")
        out = out.sort_values("date").reset_index(drop=True)
        return out
    except Exception:
        return pd.DataFrame()


def fetch_weekly_kline_akshare(code: str) -> pd.DataFrame:
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=900)).strftime("%Y%m%d")
    try:
        df = with_retry(
            ak.stock_zh_a_hist,
            symbol=code,
            period="weekly",
            start_date=start,
            end_date=end,
            adjust="qfq",
            retries=5,
        )
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
            }
        )
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df.sort_values("date").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def calc_ma_position_and_volume(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty:
        return {
            "close": None, "ma20": None, "ma60": None, "ma120": None, "ma150": None,
            "pos_vs_ma20": None, "pos_vs_ma60": None, "pos_vs_ma120": None, "pos_vs_ma150": None,
            "ma150_slope_10d": None,
            "volume_last": None, "volume_5d_avg": None, "volume_20d_avg": None,
            "volume_change_vs_5d": None, "volume_change_vs_20d": None,
            "high_12w": None, "low_12w": None, "range_12w_pct": None,
            "pullbacks_12w": [], "dry_volume_ratio": None,
        }

    close_col = pick_first(df, ["收盘", "close", "Close"])
    vol_col = pick_first(df, ["成交量", "volume", "Volume"])
    if close_col is None:
        return {
            "close": None, "ma20": None, "ma60": None, "ma120": None, "ma150": None,
            "pos_vs_ma20": None, "pos_vs_ma60": None, "pos_vs_ma120": None, "pos_vs_ma150": None,
            "ma150_slope_10d": None,
            "volume_last": None, "volume_5d_avg": None, "volume_20d_avg": None,
            "volume_change_vs_5d": None, "volume_change_vs_20d": None,
            "high_12w": None, "low_12w": None, "range_12w_pct": None,
            "pullbacks_12w": [], "dry_volume_ratio": None,
        }

    dfx = df.copy()
    dfx[close_col] = pd.to_numeric(dfx[close_col], errors="coerce")
    dfx["ma20"] = dfx[close_col].rolling(20).mean()
    dfx["ma60"] = dfx[close_col].rolling(60).mean()
    dfx["ma120"] = dfx[close_col].rolling(120).mean()
    dfx["ma150"] = dfx[close_col].rolling(150).mean()

    if vol_col:
        dfx[vol_col] = pd.to_numeric(dfx[vol_col], errors="coerce")
        dfx["vol5"] = dfx[vol_col].rolling(5).mean()
        dfx["vol20"] = dfx[vol_col].rolling(20).mean()

    last = dfx.iloc[-1]
    close = safe_float(last[close_col])
    ma20 = safe_float(last["ma20"])
    ma60 = safe_float(last["ma60"])
    ma120 = safe_float(last["ma120"])
    ma150 = safe_float(last["ma150"])
    vol_last = safe_float(last[vol_col]) if vol_col else None
    vol5 = safe_float(last["vol5"]) if "vol5" in dfx.columns else None
    vol20 = safe_float(last["vol20"]) if "vol20" in dfx.columns else None

    if "ma150" in dfx.columns and len(dfx) >= 10:
        ma150_slope_10d = safe_float(dfx["ma150"].iloc[-1] - dfx["ma150"].iloc[-10])
    else:
        ma150_slope_10d = None

    recent = dfx.tail(60)
    high_12w = safe_float(recent[close_col].max()) if not recent.empty else None
    low_12w = safe_float(recent[close_col].min()) if not recent.empty else None
    range_12w_pct = ((high_12w / low_12w) - 1) if (high_12w and low_12w) else None

    pullbacks = []
    if len(recent) >= 20:
        segs = [recent.iloc[:20], recent.iloc[20:40], recent.iloc[40:60]]
        prev_peak = None
        for seg in segs:
            if seg.empty:
                continue
            peak = safe_float(seg[close_col].max())
            trough = safe_float(seg[close_col].min())
            if peak and trough and peak != 0:
                pullbacks.append((peak - trough) / peak)
            prev_peak = peak

    return {
        "close": close,
        "ma20": ma20,
        "ma60": ma60,
        "ma120": ma120,
        "ma150": ma150,
        "pos_vs_ma20": (close / ma20 - 1) if (close and ma20) else None,
        "pos_vs_ma60": (close / ma60 - 1) if (close and ma60) else None,
        "pos_vs_ma120": (close / ma120 - 1) if (close and ma120) else None,
        "pos_vs_ma150": (close / ma150 - 1) if (close and ma150) else None,
        "ma150_slope_10d": ma150_slope_10d,
        "volume_last": vol_last,
        "volume_5d_avg": vol5,
        "volume_20d_avg": vol20,
        "volume_change_vs_5d": (vol_last / vol5 - 1) if (vol_last and vol5) else None,
        "volume_change_vs_20d": (vol_last / vol20 - 1) if (vol_last and vol20) else None,
        "high_12w": high_12w,
        "low_12w": low_12w,
        "range_12w_pct": range_12w_pct,
        "pullbacks_12w": pullbacks[-3:],
        "dry_volume_ratio": (vol_last / vol20) if (vol_last and vol20) else None,
    }


def fetch_valuation_roe_tushare(pro, code: str) -> Dict[str, Any]:
    if pro is None:
        return {"pe_ttm": None, "pb": None, "total_mv": None, "roe": None, "source": None, "status": "no_token"}
    ts_code = to_ts_code(code)
    try:
        cal = with_retry(pro.trade_cal, exchange="SSE", start_date=(datetime.now() - timedelta(days=20)).strftime("%Y%m%d"), end_date=datetime.now().strftime("%Y%m%d"), is_open="1", fields="cal_date,is_open", retries=4)
        trade_dates = []
        if cal is not None and not cal.empty and "cal_date" in cal.columns:
            trade_dates = [str(x) for x in cal["cal_date"].dropna().tolist()]
        else:
            trade_dates = [datetime.now().strftime("%Y%m%d")]

        basic = pd.DataFrame()
        for d in reversed(trade_dates):
            basic = with_retry(pro.daily_basic, ts_code=ts_code, trade_date=d, fields="ts_code,trade_date,pe_ttm,pb,total_mv", retries=3)
            if basic is not None and not basic.empty:
                break

        fin = with_retry(pro.fina_indicator, ts_code=ts_code, limit=1, fields="ts_code,end_date,roe,grossprofit_margin,netprofit_margin,or_yoy,netprofit_yoy,assets_yoy", retries=4)

        pe_ttm = pb = total_mv = roe = gross_margin = net_margin = revenue_yoy = profit_yoy = assets_yoy = None
        if basic is not None and not basic.empty:
            b = basic.iloc[0]
            pe_ttm = safe_float(b.get("pe_ttm"))
            pb = safe_float(b.get("pb"))
            total_mv = safe_float(b.get("total_mv"))
            if total_mv is not None:
                total_mv *= 10000  # 万元 -> 元
        if fin is not None and not fin.empty:
            row = fin.iloc[0]
            roe = safe_float(row.get("roe"))
            gross_margin = safe_float(row.get("grossprofit_margin"))
            net_margin = safe_float(row.get("netprofit_margin"))
            revenue_yoy = safe_float(row.get("or_yoy"))
            profit_yoy = safe_float(row.get("netprofit_yoy"))
            assets_yoy = safe_float(row.get("assets_yoy"))

        return {
            "pe_ttm": pe_ttm,
            "pb": pb,
            "total_mv": total_mv,
            "roe": roe,
            "grossprofit_margin": gross_margin,
            "netprofit_margin": net_margin,
            "revenue_yoy": revenue_yoy,
            "profit_yoy": profit_yoy,
            "assets_yoy": assets_yoy,
            "source": "tushare.daily_basic+fina_indicator",
            "status": "ok",
        }
    except Exception as e:
        return {"pe_ttm": None, "pb": None, "total_mv": None, "roe": None, "grossprofit_margin": None, "netprofit_margin": None, "revenue_yoy": None, "profit_yoy": None, "assets_yoy": None, "source": "tushare", "status": f"error:{e}"}


def fetch_20d_fund_flow_tushare(pro, code: str) -> Dict[str, Any]:
    if pro is None:
        return {"net_inflow_20d": None, "series": None, "source": None, "status": "no_token"}
    ts_code = to_ts_code(code)
    try:
        start = (datetime.now() - timedelta(days=45)).strftime("%Y%m%d")
        end = datetime.now().strftime("%Y%m%d")
        df = with_retry(
            pro.moneyflow,
            ts_code=ts_code,
            start_date=start,
            end_date=end,
            fields="ts_code,trade_date,net_mf_amount",
            retries=4,
        )
        if df is None or df.empty or "net_mf_amount" not in df.columns:
            return {"net_inflow_20d": None, "series": None, "source": "tushare.moneyflow", "status": "empty"}

        tmp = df.copy()
        tmp["trade_date"] = pd.to_datetime(tmp["trade_date"], format="%Y%m%d", errors="coerce")
        tmp["net_mf_amount"] = pd.to_numeric(tmp["net_mf_amount"], errors="coerce")
        tmp = tmp.sort_values("trade_date").tail(20)

        return {
            "net_inflow_20d": safe_float(tmp["net_mf_amount"].sum()),
            "series": [
                {"date": None if pd.isna(r.trade_date) else r.trade_date.strftime("%Y-%m-%d"), "net_inflow": safe_float(r.net_mf_amount)}
                for r in tmp.itertuples(index=False)
            ],
            "source": "tushare.moneyflow",
            "status": "ok",
        }
    except Exception as e:
        return {"net_inflow_20d": None, "series": None, "source": "tushare.moneyflow", "status": f"error:{e}"}


def fetch_inst_holding_change_tushare(pro, code: str) -> Dict[str, Any]:
    if pro is None:
        return {"inst_holding_change": None, "source": None, "status": "no_token"}
    ts_code = to_ts_code(code)
    try:
        # 使用十大流通股东作为机构持仓变化近似观察
        df = with_retry(pro.top10_floatholders, ts_code=ts_code, limit=20, retries=4)
        if df is None or df.empty:
            return {"inst_holding_change": None, "source": "tushare.top10_floatholders", "status": "empty"}

        date_col = "end_date" if "end_date" in df.columns else ("ann_date" if "ann_date" in df.columns else None)
        hold_col = "hold_amount" if "hold_amount" in df.columns else None
        if date_col is None or hold_col is None:
            return {"inst_holding_change": None, "source": "tushare.top10_floatholders", "status": "missing_columns"}

        tmp = df.copy()
        tmp[date_col] = pd.to_datetime(tmp[date_col], format="%Y%m%d", errors="coerce")
        tmp[hold_col] = pd.to_numeric(tmp[hold_col], errors="coerce")

        agg = tmp.groupby(date_col, dropna=True)[hold_col].sum().sort_index()
        if len(agg) < 2:
            return {"inst_holding_change": None, "source": "tushare.top10_floatholders", "status": "insufficient_periods"}

        last_date = agg.index[-1]
        prev_date = agg.index[-2]
        last_val = safe_float(agg.iloc[-1])
        prev_val = safe_float(agg.iloc[-2])
        delta = None
        pct = None
        if last_val is not None and prev_val is not None:
            delta = last_val - prev_val
            if prev_val != 0:
                pct = delta / prev_val

        return {
            "inst_holding_change": {
                "latest_period": last_date.strftime("%Y-%m-%d"),
                "previous_period": prev_date.strftime("%Y-%m-%d"),
                "latest_hold_amount": last_val,
                "previous_hold_amount": prev_val,
                "delta": delta,
                "delta_pct": pct,
            },
            "source": "tushare.top10_floatholders",
            "status": "ok",
        }
    except Exception as e:
        return {"inst_holding_change": None, "source": "tushare.top10_floatholders", "status": f"error:{e}"}


def calc_peg(pe_ttm: Optional[float], expected_growth_pct: Optional[float]) -> Dict[str, Any]:
    if pe_ttm is None:
        return {"expected_growth_consensus_pct": expected_growth_pct, "peg": None, "status": "missing_pe"}
    if expected_growth_pct in (None, 0):
        return {
            "expected_growth_consensus_pct": expected_growth_pct,
            "peg": None,
            "status": "unavailable",
            "reason": "缺少稳定一致预期增速，PEG不计算",
        }
    return {
        "expected_growth_consensus_pct": expected_growth_pct,
        "peg": pe_ttm / expected_growth_pct,
        "status": "ok",
    }


def calc_vcp_proxy(metrics: Dict[str, Any]) -> Dict[str, Any]:
    pullbacks = metrics.get("pullbacks_12w") or []
    contraction_count = len([x for x in pullbacks if x is not None])
    descending = None
    if len(pullbacks) >= 3:
        descending = pullbacks[-3] > pullbacks[-2] > pullbacks[-1]
    pivot = metrics.get("high_12w")
    return {
        "contraction_count": contraction_count,
        "recent_pullbacks": pullbacks,
        "descending_contractions": descending,
        "pivot_point": pivot,
        "dry_volume_ratio": metrics.get("dry_volume_ratio"),
        "stage_proxy": "stage2" if (metrics.get("pos_vs_ma150") is not None and metrics.get("pos_vs_ma150") > 0 and metrics.get("ma150_slope_10d") and metrics.get("ma150_slope_10d") > 0) else "unknown",
    }


def build_report_for_stock(code: str, name: str, spot_df: pd.DataFrame, pro) -> Dict[str, Any]:
    spot_info = {"latest_price": None, "total_market_cap": None, "pe_ttm": None, "pb": None, "roe": None, "grossprofit_margin": None, "netprofit_margin": None, "revenue_yoy": None, "profit_yoy": None, "assets_yoy": None, "source": []}
    data_quality_issues: list[str] = []

    # akshare 快照
    if spot_df is not None and not spot_df.empty and "代码" in spot_df.columns:
        row = spot_df.loc[spot_df["代码"].astype(str) == code]
        if not row.empty:
            r = row.iloc[0]
            spot_info["latest_price"] = safe_float(r.get("最新价"))
            spot_info["total_market_cap"] = safe_float(r.get("总市值"))
            spot_info["pe_ttm"] = safe_float(r.get("市盈率-动态"))
            spot_info["pb"] = safe_float(r.get("市净率"))
            spot_info["source"].append("akshare.stock_zh_a_spot_em")

    # tushare 估值/ROE兜底
    tv = fetch_valuation_roe_tushare(pro, code)
    if spot_info["pe_ttm"] is None:
        spot_info["pe_ttm"] = tv.get("pe_ttm")
    if spot_info["pb"] is None:
        spot_info["pb"] = tv.get("pb")
    if spot_info["total_market_cap"] is None:
        spot_info["total_market_cap"] = tv.get("total_mv")
    spot_info["roe"] = tv.get("roe")
    spot_info["grossprofit_margin"] = tv.get("grossprofit_margin")
    spot_info["netprofit_margin"] = tv.get("netprofit_margin")
    spot_info["revenue_yoy"] = tv.get("revenue_yoy")
    spot_info["profit_yoy"] = tv.get("profit_yoy")
    spot_info["assets_yoy"] = tv.get("assets_yoy")
    if tv.get("source"):
        spot_info["source"].append(tv.get("source"))

    # 最新价降级
    if spot_info["latest_price"] is None:
        try:
            d1 = fetch_daily_kline_tushare(pro, code, months=1)
            c = pick_first(d1, ["收盘", "close", "Close"])
            if d1 is not None and not d1.empty and c:
                spot_info["latest_price"] = safe_float(d1.iloc[-1][c])
                spot_info["source"].append("tushare.daily(last_close)")
        except Exception:
            pass

    daily = fetch_daily_kline_tushare(pro, code, months=8)
    weekly = fetch_weekly_kline_tushare(pro, code)

    if (daily is None or daily.empty or weekly is None or weekly.empty) and ENABLE_AK_FALLBACK:
        data_quality_issues.append("tushare_kline_unavailable_use_akshare_fallback")
        if daily is None or daily.empty:
            daily = fetch_daily_kline_akshare(code, months=8)
        if weekly is None or weekly.empty:
            weekly = fetch_weekly_kline_akshare(code)

    daily_metrics = calc_ma_position_and_volume(daily)
    weekly_metrics = calc_ma_position_and_volume(weekly)
    vcp_proxy = calc_vcp_proxy(daily_metrics)

    fund_flow = fetch_20d_fund_flow_tushare(pro, code)
    inst_change = fetch_inst_holding_change_tushare(pro, code)
    growth_peg = calc_peg(spot_info["pe_ttm"], expected_growth_pct=spot_info.get("profit_yoy") if spot_info.get("profit_yoy") not in (None, 0) else spot_info.get("revenue_yoy"))

    date_col = pick_first(daily, ["日期", "date"])
    recent_daily = daily.copy()
    if date_col:
        recent_daily[date_col] = pd.to_datetime(recent_daily[date_col], errors="coerce")
        recent_daily = recent_daily[recent_daily[date_col] >= (datetime.now() - timedelta(days=92))]

    if daily is None or daily.empty:
        data_quality_issues.append("missing_daily_kline")
    if weekly is None or weekly.empty:
        data_quality_issues.append("missing_weekly_kline")
    if spot_info.get("latest_price") is None:
        data_quality_issues.append("missing_latest_price")
    if spot_info.get("pe_ttm") is None:
        data_quality_issues.append("missing_pe_ttm")

    quality_score = max(0, 100 - 15 * len(data_quality_issues))

    audit_prompt_tags = {
        "damodaran": {
            "event_vs_narrative": "event优先",
            "data_confidence_hint": "财务+行情+资金流+持仓",
            "kill_switch_hint": ["revenue_yoy缺失", "profit_yoy缺失", "150日线走平/下弯", "VCP不成立"],
        },
        "serenity_logic": {
            "stage_proxy": vcp_proxy.get("stage_proxy"),
            "bottleneck_proxy": vcp_proxy.get("pivot_point"),
        },
        "tactical_execution": {
            "ma150_slope_10d": daily_metrics.get("ma150_slope_10d"),
            "pivot_point": vcp_proxy.get("pivot_point"),
            "dry_volume_ratio": vcp_proxy.get("dry_volume_ratio"),
        },
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of_date": datetime.now().strftime("%Y-%m-%d"),
        "code": code,
        "name": name,
        "snapshot": spot_info,
        "valuation_and_growth": growth_peg,
        "fund_flow_20d": fund_flow,
        "institution_holding_change": inst_change,
        "daily_ma_volume": daily_metrics,
        "weekly_ma_volume": weekly_metrics,
        "vcp_proxy": vcp_proxy,
        "audit_prompt_tags": audit_prompt_tags,
        "daily_kline_3m": recent_daily.to_dict(orient="records"),
        "data_quality": {
            "score": quality_score,
            "issues": data_quality_issues,
        },
    }


def validate_report_schema(report: Dict[str, Any]) -> bool:
    required = ["schema_version", "as_of_date", "code", "name", "snapshot", "valuation_and_growth", "fund_flow_20d", "institution_holding_change", "daily_ma_volume", "weekly_ma_volume", "daily_kline_3m", "data_quality"]
    missing = [k for k in required if k not in report]
    if missing:
        logger.error("Schema 校验失败，缺失字段: %s | code=%s", missing, report.get("code"))
        return False
    return True


def main(output_json: str = "akshare_stock_upgrade_output.json"):
    started_at = datetime.now()
    pro = get_tushare_client()
    if DATA_SOURCE == "tushare_only" and pro is None:
        logger.error("当前 data_source=tushare_only，但 Tushare 不可用。请检查 token 后重试。")
        return
    spot_df = fetch_spot_snapshot()

    if not STOCKS:
        logger.error("未配置股票池，请在 config/settings.json -> akshare_stock_upgrade.stocks 中配置")
        return

    stock_output_dir = REPORT_DIR / "stocks"
    stock_output_dir.mkdir(parents=True, exist_ok=True)

    all_reports = []
    valid_reports = 0
    for code, name in STOCKS.items():
        try:
            report = build_report_for_stock(code, name, spot_df, pro)
            if not validate_report_schema(report):
                continue
            valid_reports += 1
            all_reports.append(report)
            per_stock_path = stock_output_dir / f"{code}.json"
            per_stock_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            logger.info("完成: %s(%s) -> %s", name, code, per_stock_path)
        except Exception as e:
            logger.exception("失败: %s(%s) -> %s", name, code, e)

    output_path = REPORT_DIR / output_json
    out = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "run_summary": {
            "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": round((datetime.now() - started_at).total_seconds(), 2),
            "stock_count": len(STOCKS),
            "success_count": len(all_reports),
            "schema_valid_count": valid_reports,
            "data_source": DATA_SOURCE,
            "enable_akshare_fallback": ENABLE_AK_FALLBACK,
            "tushare_available": pro is not None,
        },
        "stocks": all_reports,
    }
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info("已输出汇总到 %s", output_path)


if __name__ == "__main__":
    main()
