import asyncio
import json
import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from playwright.async_api import BrowserContext, Error, Page, TimeoutError, async_playwright

from config.runtime import BPC_PATH, PLAYWRIGHT_USER_DATA_DIR, VIP_TXT_DUMPS_DIR, setup_logger


# ============================================================
# 核心配置区（请按本地环境调整）
# ============================================================
OUTPUT_DIR = VIP_TXT_DUMPS_DIR
INDEX_FILE = OUTPUT_DIR / "seen_urls.txt"

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "config" / "settings.json"


def load_settings() -> Dict[str, object]:
    raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    return raw.get("playwright_spider", {})


_SETTINGS = load_settings()
BLOCKED_LEADS_FILE = OUTPUT_DIR / str(_SETTINGS.get("blocked_leads_file", "Blocked_Sources_Leads_2026_05.txt"))
UA_POOL = list(_SETTINGS.get("ua_pool", []))
TRACK_KEYWORDS: Dict[str, List[str]] = dict(_SETTINGS.get("track_keywords", {}))
MAX_RETRIES = int(_SETTINGS.get("max_retries", 3))
MAX_SEEN_URLS = int(_SETTINGS.get("max_seen_urls", 20000))

TRACK_POSITIVE_GATES: Dict[str, List[str]] = {
    "Innovative_Drugs": ["fda", "clinical", "phase", "trial", "nda", "ind", "oncology", "drug", "pharma", "biotech", "cde"],
}

SITE_TRACK_PRIOR: Dict[str, List[str]] = {
    "Aviation Week AAM": ["Low_Altitude_eVTOL"],
    "SemiEngineering Packaging": ["Advanced_Substrates", "Next_Gen_Storage", "High_Speed_Interconnect"],
    "AnandTech Memory": ["Next_Gen_Storage"],
    "IEEE Spectrum Robotics": ["Humanoid_Robotics"],
    "The Robot Report": ["Humanoid_Robotics"],
}

TRACK_NEGATIVE_KEYWORDS: Dict[str, List[str]] = {
    "Innovative_Drugs": ["humanoid", "robot", "military", "combat", "drone", "evtol", "data center", "semiconductor", "gpu", "hbm"],
    "Humanoid_Robotics": ["fda", "clinical", "phase iii", "nda", "lymphoma", "drug"],
    "AI_Compute_Core": ["fda", "clinical", "phase iii", "drug"],
}

logger = setup_logger("playwright_spider")


@dataclass
class SiteConfig:
    name: str
    list_url: str
    base_url: str
    article_selectors: List[str]
    paragraph_selector: str = "p"
    title_selector: str = "h1"
    summary_selector: str = "meta[name='description']"
    content_min_chars: int = 220
    list_page_wait_ms: int = 3500


def build_site_configs() -> List[SiteConfig]:
    items = _SETTINGS.get("site_configs", [])
    configs: List[SiteConfig] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        configs.append(
            SiteConfig(
                name=str(item.get("name", "")),
                list_url=str(item.get("list_url", "")),
                base_url=str(item.get("base_url", "")),
                article_selectors=[str(x) for x in item.get("article_selectors", [])],
                paragraph_selector=str(item.get("paragraph_selector", "p")),
                title_selector=str(item.get("title_selector", "h1")),
                summary_selector=str(item.get("summary_selector", "meta[name='description']")),
                content_min_chars=int(item.get("content_min_chars", 220) or 220),
                list_page_wait_ms=int(item.get("list_page_wait_ms", 3500) or 3500),
            )
        )
    return [c for c in configs if c.name and c.list_url and c.base_url and c.article_selectors]

SITE_CONFIGS: List[SiteConfig] = build_site_configs()


async def human_sleep(low: float = 1.0, high: float = 3.0) -> None:
    await asyncio.sleep(random.uniform(low, high))


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_content(content: str) -> str:
    text = normalize_text(content)
    if not text:
        return ""

    # 先做块级噪音截断
    hard_cut_markers = [
        "These cookies are necessary for the website",
        "A decade of reporting from the frontiers",
        "Get alerted when we publish a story",
        "Your data will be processed in accordance",
    ]
    for marker in hard_cut_markers:
        idx = text.lower().find(marker.lower())
        if idx > 0:
            text = text[:idx].strip()

    noise_patterns = [
        r"subscribe now",
        r"sign up for",
        r"advertisement",
        r"cookie policy",
        r"all rights reserved",
        r"subscribe or log in to stat\+",
        r"for inquiries related to this message",
        r"provide the reference id below",
        r"privacy policy",
        r"cookie notice",
        r"terms of service",
        r"get this delivered to your inbox",
        r"global business and financial news",
        r"market data and analysis",
        r"©\s*\d{4}",
    ]
    for p in noise_patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE)

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    uniq: List[str] = []
    seen = set()
    for s in sentences:
        k = s.lower()
        if k in seen:
            continue
        if len(s) < 25:
            continue
        seen.add(k)
        uniq.append(s)

    return " ".join(uniq)


def detect_track_with_confidence(title: str, summary: str = "", site_name: str = "") -> Tuple[Optional[str], float]:
    blob = f"{title} {summary}".lower()
    best_track: Optional[str] = None
    best_score = 0.0
    site_prior = SITE_TRACK_PRIOR.get(site_name, [])

    for track, keywords in TRACK_KEYWORDS.items():
        lowered_keywords = [str(k).lower() for k in keywords]
        pos_hits = sum(1 for k in lowered_keywords if k in blob)
        if pos_hits <= 0:
            continue

        neg_keywords = [str(k).lower() for k in TRACK_NEGATIVE_KEYWORDS.get(track, [])]
        neg_hits = sum(1 for k in neg_keywords if k in blob)

        # 正向每命中1个 +1，负向每命中1个 -1.5
        raw = pos_hits - 1.5 * neg_hits
        score = max(0.0, min(1.0, raw / max(1.0, len(lowered_keywords) * 0.25)))

        # 赛道强白名单门槛（先验约束）
        gates = [g.lower() for g in TRACK_POSITIVE_GATES.get(track, [])]
        if gates and not any(g in blob for g in gates):
            score *= 0.25

        # 站点赛道先验加权
        if site_prior:
            if track in site_prior:
                score *= 1.25
            else:
                score *= 0.75

        if score > best_score:
            best_score = score
            best_track = track

    if best_track is None:
        return None, 0.0
    return best_track, round(best_score, 3)


def output_file_for_track(track_name: str) -> Path:
    return OUTPUT_DIR / f"{track_name}_Insights_2026_05.txt"


def canonical_url(url: str) -> str:
    return url.split("?")[0].strip().rstrip("/")


def is_valid_article_url(cfg: SiteConfig, url: str) -> bool:
    u = canonical_url(url).lower()

    # 通用剔除
    blocked_tokens = [
        "/staff/",
        "/author/",
        "/category/",
        "/tag/",
        "/topics/",
        "/newsletter",
        "/about",
        "/contact",
    ]
    if any(t in u for t in blocked_tokens):
        return False

    # 站点级规则
    if cfg.name == "Stat News":
        # 只保留带日期路径的文章
        if not re.search(r"/202\d/\d{2}/\d{2}/", u):
            return False
    if cfg.name == "Reuters Tech":
        if "/technology/" not in u and "/world/" not in u:
            return False
    if cfg.name == "CNBC Tech":
        if "cnbc.com/" not in u:
            return False
        if "/video/" in u or "/live-tv/" in u:
            return False
    if cfg.name == "VentureBeat AI":
        if "venturebeat.com" not in u:
            return False
        if "/tag/" in u or "/category/" in u:
            return False
    if cfg.name == "WSJ Tech":
        if "wsj.com" not in u:
            return False
        if "/livecoverage/" in u or "/podcast/" in u or "/video/" in u:
            return False
        if "/articles/" not in u and "/tech/" not in u:
            return False
    if cfg.name == "TechCrunch AI":
        if "techcrunch.com" not in u:
            return False
        if "/video/" in u or "/tag/" in u:
            return False
    if cfg.name == "The Register AI":
        if "theregister.com" not in u:
            return False
        if "/tag/" in u or "/topic/" in u:
            return False

    return True


def is_low_quality_content(text: str) -> bool:
    t = text.lower()
    low_quality_signals = [
        "for inquiries related to this message",
        "provide the reference id",
        "get the most important global markets news",
        "subscribe or log in to stat+",
        "a decade of reporting from the frontiers",
        "these cookies are necessary for the website",
    ]
    hit = sum(1 for s in low_quality_signals if s in t)
    return hit >= 2


def load_seen_urls(index_path: Path) -> list[str]:
    if not index_path.exists():
        return []
    with index_path.open("r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def append_seen_url(index_path: Path, url: str) -> None:
    with index_path.open("a", encoding="utf-8") as f:
        f.write(f"{url}\n")


def prune_seen_urls(index_path: Path, seen_url_order: list[str], max_size: int = MAX_SEEN_URLS) -> list[str]:
    if len(seen_url_order) <= max_size:
        return seen_url_order

    kept = seen_url_order[-max_size:]
    with index_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(kept) + "\n")

    logger.info("[INFO] URL索引已裁剪: %s -> %s", len(seen_url_order), len(kept))
    return kept


def append_to_file(path: Path, article_url: str, article_title: str, content: str, track_confidence: float) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = (
        f"\n\n{'=' * 80}\n"
        f"时间: {now}\n"
        f"标题: {article_title}\n"
        f"链接: {article_url}\n"
        f"赛道置信度: {track_confidence:.3f}\n"
        f"内容:\n{content}\n"
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(block)


def append_blocked_leads(path: Path, site_name: str, leads: List[Tuple[str, str]]) -> None:
    if not leads:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n{'=' * 80}\n时间: {now}\n来源: {site_name}\n")
        for title, url in leads:
            f.write(f"- {title}\n  {url}\n")


async def detect_blocked_activity(page: Page) -> bool:
    try:
        txt = (await page.content()).lower()
    except Exception:
        return False

    markers = [
        "access is temporarily restricted",
        "unusual activity",
        "automated activity",
        "verify you are a human",
        "please verify",
    ]
    return any(m in txt for m in markers)


async def harden_page(page: Page) -> None:
    ua = random.choice(UA_POOL)
    await page.set_extra_http_headers({"User-Agent": ua})
    await page.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        window.chrome = window.chrome || { runtime: {} };
        """
    )


async def page_health_check(page: Page) -> bool:
    try:
        title = await page.title()
        ready = await page.evaluate("() => document.readyState")
        if ready not in {"interactive", "complete"}:
            return False
        if not title and "about:blank" in page.url:
            return False
        return True
    except Exception:
        return False


async def safe_goto(page: Page, url: str, site_name: str, retries: int = MAX_RETRIES) -> bool:
    for attempt in range(1, retries + 1):
        try:
            await human_sleep(1, 3)
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            await human_sleep(1, 3)
            if await page_health_check(page):
                logger.info("[OK] 已进入 %s: %s", site_name, url)
                return True
            logger.warning("[WARN] 页面健康检查失败: %s, attempt=%s", site_name, attempt)
        except (TimeoutError, Error) as e:
            logger.error("[ERR] 进入站点失败(%s) attempt=%s: %s", site_name, attempt, e)
        if attempt < retries:
            await human_sleep(2, 5)
    return False


async def extract_core_text(page: Page, cfg: SiteConfig) -> str:
    await asyncio.sleep(cfg.list_page_wait_ms / 1000)

    title = ""
    try:
        title = normalize_text(await page.locator(cfg.title_selector).first.inner_text())
    except Exception:
        title = ""

    summary = ""
    try:
        summary = normalize_text(await page.locator(cfg.summary_selector).first.get_attribute("content") or "")
    except Exception:
        summary = ""

    paragraphs = await page.locator(cfg.paragraph_selector).all_inner_texts()
    paragraphs = [normalize_text(p) for p in paragraphs if normalize_text(p)]

    # 过滤长度过短段落并跳过前两段导言
    filtered = [p for p in paragraphs if len(p) > 40]
    core = filtered[2:] if len(filtered) > 2 else filtered
    merged = clean_content("\n".join(core))

    if summary and summary not in merged:
        merged = f"{summary}\n\n{merged}".strip()
    if title and title not in merged:
        merged = f"{title}\n\n{merged}".strip()

    return merged

async def collect_article_links(page: Page, cfg: SiteConfig) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []

    try:
        await human_sleep(1, 3)
        for sel in cfg.article_selectors:
            anchors = page.locator(sel)
            count = await anchors.count()
            for i in range(min(count, 120)):
                try:
                    node = anchors.nth(i)
                    title = normalize_text(await node.inner_text())
                    href = await node.get_attribute("href")

                    if not title:
                        aria_label = await node.get_attribute("aria-label")
                        title_attr = await node.get_attribute("title")
                        title = normalize_text(aria_label or title_attr or "")

                    if not href:
                        continue

                    href = urljoin(cfg.base_url, href)

                    if not title:
                        title = href.rsplit("/", maxsplit=1)[-1].replace("-", " ")

                    if href.startswith("http") and len(title) > 6:
                        links.append((title, href))
                except Exception:
                    continue

        seen = set()
        uniq_links = []
        for t, u in links:
            key = canonical_url(u)
            if key in seen:
                continue
            if not is_valid_article_url(cfg, key):
                continue
            seen.add(key)
            uniq_links.append((t, u))

        logger.info("[OK] %s 列表扫描完成，候选数量: %s", cfg.name, len(uniq_links))
        return uniq_links
    except Exception as e:  # noqa: BLE001
        logger.error("[ERR] 列表扫描失败(%s): %s", cfg.name, e)
        return []


async def reopen_page(context: BrowserContext, old_page: Page) -> Page:
    try:
        await old_page.close()
    except Exception:
        pass
    new_page = await context.new_page()
    await harden_page(new_page)
    return new_page


async def process_site(
    context: BrowserContext,
    page: Page,
    cfg: SiteConfig,
    seen_url_set: set[str],
    seen_url_order: list[str],
) -> Dict[str, int | str | bool]:
    stats: Dict[str, int | str | bool] = {
        "site": cfg.name,
        "entry_ok": False,
        "blocked": 0,
        "candidates": 0,
        "matched": 0,
        "skipped_seen": 0,
        "saved": 0,
        "low_quality": 0,
        "extract_errors": 0,
        "goto_failures": 0,
    }

    ok = await safe_goto(page, cfg.list_url, cfg.name)
    if not ok:
        stats["goto_failures"] = int(stats["goto_failures"]) + 1
        logger.error("[ALERT] 入口访问失败: 站点=%s URL=%s", cfg.name, cfg.list_url)
        return stats

    stats["entry_ok"] = True
    leads_only_sites = {"Reuters Tech", "WSJ Tech"}
    is_blocked = await detect_blocked_activity(page)

    if cfg.name in leads_only_sites:
        candidates = await collect_article_links(page, cfg)
        stats["candidates"] = len(candidates)
        append_blocked_leads(BLOCKED_LEADS_FILE, cfg.name, candidates[:50])
        if is_blocked:
            stats["blocked"] = 1
            logger.warning("[BLOCKED] %s 检测到限制页面，已降级为线索模式。", cfg.name)
        else:
            logger.info("[LEADS] %s 使用线索模式，跳过正文抓取。", cfg.name)
        return stats

    candidates = await collect_article_links(page, cfg)
    stats["candidates"] = len(candidates)
    if not candidates:
        logger.info("[INFO] %s 无候选链接", cfg.name)
        return stats

    consecutive_empty_extracts = 0
    for title, url in candidates:
        track, track_confidence = detect_track_with_confidence(title, site_name=cfg.name)
        if not track or track_confidence < 0.25:
            continue

        stats["matched"] = int(stats["matched"]) + 1
        url_key = canonical_url(url)
        if url_key in seen_url_set:
            stats["skipped_seen"] = int(stats["skipped_seen"]) + 1
            logger.info("[SKIP] 已抓取，跳过: %s", url_key)
            continue

        logger.info("[HIT] 命中关键词文章: %s -> %s", title, track)

        enter_ok = await safe_goto(page, url, cfg.name)
        if not enter_ok:
            stats["goto_failures"] = int(stats["goto_failures"]) + 1
            continue

        try:
            content = await extract_core_text(page, cfg)
            if (not content) or len(content) < cfg.content_min_chars or is_low_quality_content(content):
                stats["low_quality"] = int(stats["low_quality"]) + 1
                consecutive_empty_extracts += 1
                logger.warning("[WARN] 正文质量不足/疑似订阅墙内容 (%s/3): %s", consecutive_empty_extracts, url)
            else:
                consecutive_empty_extracts = 0
                outfile = output_file_for_track(track)
                append_to_file(outfile, url, title, content, track_confidence)
                append_seen_url(INDEX_FILE, url_key)
                seen_url_set.add(url_key)
                seen_url_order.append(url_key)
                stats["saved"] = int(stats["saved"]) + 1
                logger.info("[SAVE] 已写入: %s", outfile)
        except Exception as e:  # noqa: BLE001
            stats["extract_errors"] = int(stats["extract_errors"]) + 1
            consecutive_empty_extracts += 1
            logger.error("[ERR] 正文抓取异常 (%s/3): %s, error=%s", consecutive_empty_extracts, url, e)

        if consecutive_empty_extracts >= 3:
            try:
                await page.screenshot(path="error.png", full_page=True)
                logger.error("[ALERT] DOM疑似断裂: 站点=%s 连续3次正文提取失败，URL=%s，已保存 error.png", cfg.name, url)
                page = await reopen_page(context, page)
                await safe_goto(page, cfg.list_url, cfg.name)
            except Exception as e:  # noqa: BLE001
                logger.error("[ERR] 截图/告警/恢复失败: %s", e)
            finally:
                consecutive_empty_extracts = 0

        try:
            await human_sleep(1, 2)
            await page.go_back(wait_until="domcontentloaded", timeout=60000)
        except Exception:
            await safe_goto(page, cfg.list_url, cfg.name)

    return stats


async def build_persistent_context(playwright) -> BrowserContext:
    launch_args = [
        f"--disable-extensions-except={BPC_PATH}",
        f"--load-extension={BPC_PATH}",
        "--disable-blink-features=AutomationControlled",
    ]

    init_ua = random.choice(UA_POOL)
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(PLAYWRIGHT_USER_DATA_DIR),
        headless=False,
        args=launch_args,
        user_agent=init_ua,
        viewport={"width": 1440, "height": 900},
        locale="en-US",
        timezone_id="America/New_York",
    )
    return context


async def main() -> None:
    started_at = datetime.now()
    logger.info("[BOOT] 启动增强版机构级防御爬虫...")
    seen_url_order = load_seen_urls(INDEX_FILE)
    seen_url_set = set(seen_url_order)
    logger.info("[INFO] 已加载历史URL索引: %s 条", len(seen_url_order))

    site_stats: List[Dict[str, int | str | bool]] = []
    async with async_playwright() as p:
        context = await build_persistent_context(p)
        try:
            pages = [await context.new_page() for _ in SITE_CONFIGS]
            for page in pages:
                await harden_page(page)

            site_stats = await asyncio.gather(
                *(
                    process_site(context, pages[idx], cfg, seen_url_set, seen_url_order)
                    for idx, cfg in enumerate(SITE_CONFIGS)
                )
            )
        finally:
            await context.close()

    seen_url_order = prune_seen_urls(INDEX_FILE, seen_url_order, MAX_SEEN_URLS)
    run_summary = {
        "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round((datetime.now() - started_at).total_seconds(), 2),
        "seen_url_count": len(seen_url_order),
        "site_stats": site_stats,
        "totals": {
            "sites": len(site_stats),
            "candidates": sum(int(s.get("candidates", 0)) for s in site_stats),
            "matched": sum(int(s.get("matched", 0)) for s in site_stats),
            "saved": sum(int(s.get("saved", 0)) for s in site_stats),
            "low_quality": sum(int(s.get("low_quality", 0)) for s in site_stats),
            "extract_errors": sum(int(s.get("extract_errors", 0)) for s in site_stats),
            "goto_failures": sum(int(s.get("goto_failures", 0)) for s in site_stats),
        },
    }
    (OUTPUT_DIR / "playwright_spider_run_summary.json").write_text(
        json.dumps(run_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[INFO] 当前URL索引规模: %s", len(seen_url_order))
    logger.info("[DONE] 抓取流程结束。")


if __name__ == "__main__":
    asyncio.run(main())
