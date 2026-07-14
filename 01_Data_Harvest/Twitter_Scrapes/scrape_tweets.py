import json
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

# 可配置项
TWITTER_HANDLES = ["aleabitoreddit"]
MAX_ITEMS_PER_HANDLE = 30
NITTER_BASE_URL = "https://nitter.net"
OUTPUT_FILE = "serenity_tweets.json"


def fetch_rss(handle: str):
    url = f"{NITTER_BASE_URL}/{handle}/rss"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        },
    )

    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def parse_rss(xml_bytes: bytes, handle: str, max_items: int):
    root = ET.fromstring(xml_bytes)
    items = root.findall("./channel/item")

    results = []
    for item in items[:max_items]:
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub_date_raw = item.findtext("pubDate") or ""
        description = item.findtext("description") or ""

        try:
            pub_date = parsedate_to_datetime(pub_date_raw).isoformat() if pub_date_raw else None
        except Exception:
            pub_date = pub_date_raw or None

        results.append(
            {
                "username": handle,
                "text": title,
                "url": link,
                "published_at": pub_date,
                "description": description,
                "source": "nitter_rss",
            }
        )

    return results


def main():
    all_tweets = []

    print("开始抓取推文（Nitter RSS 方案）...")
    for handle in TWITTER_HANDLES:
        try:
            xml_data = fetch_rss(handle)
            tweets = parse_rss(xml_data, handle, MAX_ITEMS_PER_HANDLE)
            all_tweets.extend(tweets)
            print(f"{handle}: 抓取到 {len(tweets)} 条")
        except Exception as e:
            print(f"{handle}: 抓取失败 -> {e}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_tweets, f, ensure_ascii=False, indent=2)

    print(f"完成，已保存 {len(all_tweets)} 条到 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
