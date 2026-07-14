import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pdfplumber
import requests
import tushare as ts
import tushare.pro.client as client

client.DataApi._DataApi__http_url = "http://api.quicksync.cn"

from config.runtime import LOOKBACK_DAYS, MAX_WORKERS, REPORT_DIR, setup_logger
from config.secrets import TUSHARE_TOKEN


logger = setup_logger("a_share_fundamental_extractor")
SETTINGS_FILE = Path(__file__).resolve().parent.parent / "config" / "settings.json"

# =========================
# 全局配置区（可按需修改）
# =========================
SETTINGS = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("a_share_fundamental_extractor", {})
TARGET_TS_CODES = [str(x).strip().upper() for x in SETTINGS.get("target_ts_codes", ["002179.SZ"]) if str(x).strip()]
INDEX_FILE = REPORT_DIR / "report_index.json"
FAILED_REPORTS_FILE = REPORT_DIR / "failed_reports.json"
RUN_STATE_FILE = REPORT_DIR / "a_share_run_state.json"

MAX_RETRIES = 3
RETRY_SLEEP = 2
TIMEOUT = 25
MAX_PDF_PAGES = int(SETTINGS.get("max_pdf_pages", 300))
CHUNK_SIZE_PAGES = int(SETTINGS.get("chunk_size_pages", 80))

# 智能过滤规则
WHITELIST = ["年度报告", "投资者关系", "可行性分析"]
BLACKLIST = ["摘要", "英文", "取消", "延期", "提示性", "回复公告"]


# =========================
# 通用工具
# =========================
def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_date_str(v: Any) -> str:
    """将日期字段统一为可排序字符串（YYYYMMDD 或 ISO 字符串）。"""
    if v is None:
        return ""
    s = str(v).strip()
    return re.sub(r"[^0-9]", "", s)[:14] or s


def sanitize_filename(name: str) -> str:
    """将公告标题转为安全文件名。"""
    name = re.sub(r"[\\/:*?\"<>|\n\r\t]+", "_", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name[:120] or "report"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def record_key(ts_code: str, report_type: str, title: str, ann_date: Any, pdf_url: str) -> str:
    raw = f"{ts_code}|{report_type}|{title}|{normalize_date_str(ann_date)}|{pdf_url}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_run_state() -> Dict[str, Any]:
    if not RUN_STATE_FILE.exists():
        return {"downloaded": {}, "parsed": {}}
    try:
        return json.loads(RUN_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"downloaded": {}, "parsed": {}}


def save_run_state(state: Dict[str, Any]) -> None:
    RUN_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# =========================
# 模块一：Tushare 智能研报定位下载器
# =========================
def init_tushare(token: str):
    """初始化 Tushare API。"""
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
    except Exception as e:
        raise RuntimeError(f"[-] Tushare 初始化失败：{e}")


def safe_tushare_call(func, *args, **kwargs):
    """带重试机制的 Tushare 调用。"""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            print(f"[!] Tushare 请求失败，重试中 ({attempt}/{MAX_RETRIES}) -> {e}")
            time.sleep(RETRY_SLEEP)
    raise RuntimeError(f"[-] Tushare 请求连续失败，终止执行：{last_err}")


def fetch_announcements_compatible(pro, ts_code: str, lookback_days: int = 365) -> List[Dict[str, Any]]:
    """
    公告抓取兼容层：
    - 优先尝试 pro.anns（较常见）
    - 兜底尝试 pro.announcements（部分环境命名差异）
    并统一字段命名。
    """
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")

    print(f"[+] {now_ts()} | 正在拉取 {ts_code} 自 {start_date} 至 {end_date} 的公告流...")

    candidates = [
        ("anns", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
        ("announcements", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}),
    ]

    raw_df = None
    used_api = None

    for api_name, params in candidates:
        api_func = getattr(pro, api_name, None)
        if api_func is None:
            continue
        try:
            raw_df = safe_tushare_call(api_func, **params)
            used_api = api_name
            break
        except Exception as e:
            print(f"[!] 接口 {api_name} 调用失败，尝试下一个兼容接口 -> {e}")

    if raw_df is None or raw_df.empty:
        print(f"[!] {ts_code} 未检索到公告数据，请检查权限或日期区间。")
        return []

    records = raw_df.to_dict(orient="records")
    normalized = []

    for r in records:
        title = r.get("title") or r.get("ann_title") or r.get("name") or ""
        ann_date = r.get("ann_date") or r.get("pub_date") or r.get("datetime") or ""
        url = r.get("url") or r.get("pdf") or r.get("ann_url") or r.get("file_url") or ""

        normalized.append(
            {
                "ts_code": r.get("ts_code") or ts_code,
                "ann_date": ann_date,
                "title": str(title),
                "url": str(url),
                "raw": r,
                "source_api": used_api,
            }
        )

    print(f"[+] {ts_code} 公告抓取完成，共 {len(normalized)} 条（接口：{used_api}）。")
    return normalized


def is_valid_title(title: str) -> bool:
    """白名单 + 黑名单过滤。"""
    if not title:
        return False
    hit_white = any(k in title for k in WHITELIST)
    hit_black = any(k in title for k in BLACKLIST)
    return hit_white and (not hit_black)


def pick_targets(records: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    过滤并选择：
    1) 最新年度报告
    2) 最新投资者关系活动记录
    """
    filtered = [r for r in records if is_valid_title(r.get("title", ""))]

    if not filtered:
        return None, None, []

    filtered.sort(key=lambda x: normalize_date_str(x.get("ann_date")), reverse=True)

    latest_annual = None
    latest_ir = None

    for r in filtered:
        title = str(r.get("title", ""))
        if latest_annual is None and "年度报告" in title:
            latest_annual = r
        if latest_ir is None and ("投资者关系" in title or "投资者关系活动记录" in title):
            latest_ir = r
        if latest_annual and latest_ir:
            break

    return latest_annual, latest_ir, filtered


def safe_download(url: str, output_path: Path) -> bool:
    """带重试的 PDF 下载。"""
    last_err = None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with requests.get(url, headers=headers, timeout=TIMEOUT, stream=True) as resp:
                resp.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            f.write(chunk)
            return True
        except Exception as e:
            last_err = e
            print(f"[!] 下载失败，重试中 ({attempt}/{MAX_RETRIES}) -> {e}")
            time.sleep(RETRY_SLEEP)

    print(f"[-] 下载彻底失败：{output_path.name} -> {last_err}")
    return False


def resolve_pdf_url(record: Dict[str, Any]) -> Optional[str]:
    """从标准字段和 raw 字段中尽量提取 PDF 原始链接。"""
    for key in ["url", "pdf", "ann_url", "file_url"]:
        v = record.get(key)
        if isinstance(v, str) and v.lower().startswith("http") and ".pdf" in v.lower():
            return v

    raw = record.get("raw", {}) if isinstance(record.get("raw"), dict) else {}
    for key in ["url", "pdf", "ann_url", "file_url"]:
        v = raw.get(key)
        if isinstance(v, str) and v.lower().startswith("http") and ".pdf" in v.lower():
            return v

    return None


def download_target_reports(
    ts_code: str,
    latest_annual: Optional[Dict[str, Any]],
    latest_ir: Optional[Dict[str, Any]],
    run_state: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """下载目标文件并返回结构化下载结果。"""
    ensure_dir(REPORT_DIR)
    results: List[Dict[str, Any]] = []

    targets = [
        ("年度报告", latest_annual),
        ("投资者关系活动记录", latest_ir),
    ]

    for report_type, item in targets:
        if not item:
            print(f"[!] {ts_code} 未锁定到目标：{report_type}")
            results.append(
                {
                    "ts_code": ts_code,
                    "report_type": report_type,
                    "status": "not_found",
                }
            )
            continue

        title = str(item.get("title", report_type))
        pdf_url = resolve_pdf_url(item)

        if not pdf_url:
            print(f"[!] {ts_code} {report_type} 未找到可用 PDF 链接，标题：{title}")
            results.append(
                {
                    "ts_code": ts_code,
                    "report_type": report_type,
                    "status": "missing_url",
                    "title": title,
                    "ann_date": item.get("ann_date"),
                }
            )
            continue

        filename = f"{ts_code}_{sanitize_filename(title)}.pdf"
        output_path = REPORT_DIR / filename
        dedupe_key = record_key(ts_code, report_type, title, item.get("ann_date"), pdf_url)

        downloaded_state = run_state.setdefault("downloaded", {})
        if dedupe_key in downloaded_state and output_path.exists():
            logger.info("[RESUME] 命中断点续跑，跳过下载: %s", output_path.name)
            results.append(
                {
                    "ts_code": ts_code,
                    "report_type": report_type,
                    "status": "already_downloaded",
                    "title": title,
                    "ann_date": item.get("ann_date"),
                    "pdf_url": pdf_url,
                    "pdf_path": str(output_path.resolve()),
                    "dedupe_key": dedupe_key,
                }
            )
            continue

        logger.info("成功锁定目标文件：%s | %s", ts_code, title)
        logger.info("开始下载 -> %s", pdf_url)
        ok = safe_download(pdf_url, output_path)

        if ok:
            downloaded_state[dedupe_key] = {
                "pdf_path": str(output_path.resolve()),
                "title": title,
                "ann_date": item.get("ann_date"),
                "updated_at": now_ts(),
            }

        results.append(
            {
                "ts_code": ts_code,
                "report_type": report_type,
                "status": "downloaded" if ok else "download_failed",
                "title": title,
                "ann_date": item.get("ann_date"),
                "pdf_url": pdf_url,
                "pdf_path": str(output_path.resolve()) if ok else None,
                "dedupe_key": dedupe_key,
            }
        )

        if ok:
            logger.info("下载完成：%s", output_path)

    return results


# =========================
# 模块二：PDF 极速脱水转 TXT 工具
# =========================
def clean_page_text(text: str) -> str:
    """清洗单页文本：去空行、去乱码字符、去疑似页码行。"""
    if not text:
        return ""

    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    lines = text.splitlines()
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if re.fullmatch(r"\d{1,4}", s):
            continue
        if re.fullmatch(r"[-—_\s]*\d{1,4}[-—_\s]*", s):
            continue
        cleaned.append(s)

    return "\n".join(cleaned)


def extract_mda_section(text: str) -> str:
    """尝试截取“管理层讨论与分析”章节。"""
    start_patterns = [r"管理层讨论与分析", r"董事会报告"]
    end_patterns = [r"公司治理", r"重要事项", r"财务报告", r"监事会报告"]

    start_pos = None
    for p in start_patterns:
        m = re.search(p, text)
        if m:
            start_pos = m.start()
            break

    if start_pos is None:
        return text

    sub = text[start_pos:]
    end_pos = None
    for p in end_patterns:
        m = re.search(p, sub)
        if m and m.start() > 200:
            end_pos = m.start()
            break

    return sub if end_pos is None else sub[:end_pos]


def pdf_to_txt(pdf_path: Path) -> Optional[Path]:
    """PDF 转 TXT 主函数。"""
    if not pdf_path.exists():
        logger.error("文件不存在：%s", pdf_path)
        return None

    txt_path = pdf_path.with_suffix(".txt")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("正在执行 PDF 转 TXT：%s", pdf_path.name)
            all_text_parts = []

            with pdfplumber.open(str(pdf_path)) as pdf:
                total_pages = len(pdf.pages)
                limited_pages = min(total_pages, MAX_PDF_PAGES)
                if total_pages > MAX_PDF_PAGES:
                    logger.warning("超大 PDF，触发页数上限: total=%s limited=%s file=%s", total_pages, limited_pages, pdf_path.name)

                for chunk_start in range(0, limited_pages, CHUNK_SIZE_PAGES):
                    chunk_end = min(chunk_start + CHUNK_SIZE_PAGES, limited_pages)
                    for page_index in range(chunk_start, chunk_end):
                        page = pdf.pages[page_index]
                        page_text = clean_page_text(page.extract_text() or "")
                        if page_text:
                            all_text_parts.append(page_text)
                    logger.info("已处理页段: %s-%s / %s", chunk_start + 1, chunk_end, limited_pages)

            merged_text = "\n\n".join(all_text_parts)

            if "年度报告" in pdf_path.name:
                mda = extract_mda_section(merged_text)
                if mda and len(mda) > 1000:
                    merged_text = mda
                    logger.info("检测为年度报告，已优先抽取管理层讨论与分析章节。")

            merged_text = re.sub(r"\n{3,}", "\n\n", merged_text).strip()

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(merged_text)

            logger.info("TXT 输出完成：%s", txt_path)
            return txt_path

        except Exception as e:
            logger.warning("PDF 解析失败，重试中 (%s/%s) -> %s", attempt, MAX_RETRIES, e)
            time.sleep(RETRY_SLEEP)

    logger.error("PDF 转换失败：%s", pdf_path.name)
    return None


# =========================
# 流程编排：批量处理 + JSON 索引
# =========================
def process_single_stock(pro, ts_code: str, run_state: Dict[str, Any]) -> Dict[str, Any]:
    """处理单个股票代码的完整流程。"""
    result: Dict[str, Any] = {
        "ts_code": ts_code,
        "started_at": now_ts(),
        "candidates": 0,
        "selected": {},
        "downloads": [],
        "txt_outputs": [],
        "status": "unknown",
        "error": None,
    }

    try:
        records = fetch_announcements_compatible(pro, ts_code, LOOKBACK_DAYS)
        latest_annual, latest_ir, filtered = pick_targets(records)

        result["candidates"] = len(filtered)
        result["selected"] = {
            "annual": latest_annual.get("title") if latest_annual else None,
            "ir": latest_ir.get("title") if latest_ir else None,
        }

        logger.info("%s | 过滤后候选公告数：%s", ts_code, len(filtered))

        download_results = download_target_reports(ts_code, latest_annual, latest_ir, run_state)
        result["downloads"] = download_results

        parsed_state = run_state.setdefault("parsed", {})
        failed_items: List[Dict[str, Any]] = []
        for item in download_results:
            pdf_path = item.get("pdf_path")
            dedupe_key = item.get("dedupe_key")
            if item.get("status") in {"downloaded", "already_downloaded"} and pdf_path and dedupe_key:
                existing_txt = parsed_state.get(dedupe_key, {}).get("txt_path")
                if existing_txt and Path(existing_txt).exists():
                    logger.info("[RESUME] 命中断点续跑，跳过解析: %s", Path(existing_txt).name)
                    result["txt_outputs"].append(existing_txt)
                    continue

                txt_path = pdf_to_txt(Path(pdf_path))
                if txt_path:
                    parsed_state[dedupe_key] = {"txt_path": str(txt_path.resolve()), "updated_at": now_ts()}
                    result["txt_outputs"].append(str(txt_path.resolve()))
                else:
                    failed_items.append(item)

        result["failed_reports"] = failed_items

        result["status"] = "ok"
        result["finished_at"] = now_ts()
        return result

    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        result["finished_at"] = now_ts()
        print(f"[-] {ts_code} 处理失败：{e}")
        return result


def save_index(index_payload: Dict[str, Any]) -> None:
    """保存结构化 JSON 索引。"""
    ensure_dir(REPORT_DIR)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index_payload, f, ensure_ascii=False, indent=2)
    print(f"[+] 结构化索引已输出：{INDEX_FILE.resolve()}")


def main():
    started_at = datetime.now()
    logger.info("%s", "=" * 72)
    logger.info("A 股基本面自动化提取引擎启动：Tushare 智能定位 + PDF 极速脱水（增强版）")
    logger.info("%s", "=" * 72)

    if not TUSHARE_TOKEN or "YOUR_" in TUSHARE_TOKEN:
        logger.error("请先在 config/secrets.py 中配置真实 TUSHARE_TOKEN，再执行。")
        return

    try:
        pro = init_tushare(TUSHARE_TOKEN)
    except Exception as e:
        print(e)
        return

    ts_codes = [c.strip().upper() for c in TARGET_TS_CODES if c and c.strip()]
    if not ts_codes:
        logger.error("TARGET_TS_CODES 为空，请至少配置一个股票代码。")
        return

    logger.info("本次任务股票池：%s", ts_codes)
    logger.info("并发线程数：%s", MAX_WORKERS)

    run_state = load_run_state()
    all_results: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(ts_codes))) as ex:
        future_map = {ex.submit(process_single_stock, pro, code, run_state): code for code in ts_codes}
        for fut in as_completed(future_map):
            code = future_map[fut]
            try:
                all_results.append(fut.result())
                logger.info("%s 任务线程收敛完成。", code)
            except Exception as e:
                logger.error("%s 线程异常：%s", code, e)
                all_results.append(
                    {
                        "ts_code": code,
                        "status": "failed",
                        "error": str(e),
                        "started_at": now_ts(),
                        "finished_at": now_ts(),
                    }
                )

    ok_count = sum(1 for x in all_results if x.get("status") == "ok")
    fail_count = len(all_results) - ok_count

    index_payload = {
        "generated_at": now_ts(),
        "config": {
            "lookback_days": LOOKBACK_DAYS,
            "whitelist": WHITELIST,
            "blacklist": BLACKLIST,
            "report_dir": str(REPORT_DIR.resolve()),
            "max_retries": MAX_RETRIES,
            "retry_sleep": RETRY_SLEEP,
            "timeout": TIMEOUT,
            "max_workers": MAX_WORKERS,
        },
        "summary": {
            "total": len(all_results),
            "ok": ok_count,
            "failed": fail_count,
        },
        "results": all_results,
    }

    save_index(index_payload)
    save_run_state(run_state)

    failed_reports = []
    for stock_result in all_results:
        for item in stock_result.get("failed_reports", []):
            failed_reports.append({"ts_code": stock_result.get("ts_code"), **item})
    FAILED_REPORTS_FILE.write_text(json.dumps(failed_reports, ensure_ascii=False, indent=2), encoding="utf-8")

    run_summary_path = REPORT_DIR / "a_share_run_summary.json"
    run_summary_path.write_text(
        json.dumps(
            {
                "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "elapsed_seconds": round((datetime.now() - started_at).total_seconds(), 2),
                "total": len(all_results),
                "ok": ok_count,
                "failed": fail_count,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    logger.info("全流程执行完毕：成功 %s，失败 %s，总计 %s", ok_count, fail_count, len(all_results))
    logger.info("你可以直接读取 report_index.json 做后续研究管道拼接。")
    logger.info("run summary: %s", run_summary_path)
    logger.info("%s", "=" * 72)


if __name__ == "__main__":
    main()
