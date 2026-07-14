#!/usr/bin/env python3
"""
从 VIP_Txt_Dumps 提取高置信赛道信号，生成 themes.json
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from config.runtime import PROJECT_ROOT, REPORT_DIR

VIP_DIR = PROJECT_ROOT / "01_Data_Harvest" / "VIP_Txt_Dumps"
OUT_PATH = REPORT_DIR / "themes.json"

TRACK_FILE_RE = re.compile(r"^(?P<track>[A-Za-z0-9_]+)_Insights_\d{4}_\d{2}\.txt$")
CONF_RE = re.compile(r"赛道置信度:\s*([0-9.]+)")
TITLE_RE = re.compile(r"标题:\s*(.+)")


def split_blocks(text: str) -> List[str]:
    return [b.strip() for b in text.split("=" * 80) if b.strip()]


def extract_track_from_filename(path: Path) -> str | None:
    m = TRACK_FILE_RE.match(path.name)
    return m.group("track") if m else None


def parse_block(block: str) -> Dict[str, Any]:
    c = CONF_RE.search(block)
    t = TITLE_RE.search(block)
    conf = float(c.group(1)) if c else None
    title = t.group(1).strip() if t else ""
    return {"confidence": conf, "title": title}


def top_keywords(titles: List[str], n: int = 8) -> List[str]:
    stop = {"the", "and", "for", "with", "from", "into", "this", "that", "will", "are", "its", "in", "of"}
    counter: Counter[str] = Counter()
    for title in titles:
        for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", title.lower()):
            if w in stop:
                continue
            counter[w] += 1
    return [k for k, _ in counter.most_common(n)]


def build_themes() -> Dict[str, Any]:
    by_track = defaultdict(list)

    for p in VIP_DIR.glob("*_Insights_*.txt"):
        track = extract_track_from_filename(p)
        if not track:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for block in split_blocks(text):
            item = parse_block(block)
            conf = item["confidence"]
            if conf is None or conf < 0.35:
                continue
            by_track[track].append(item)

    themes = []
    for track, items in by_track.items():
        if not items:
            continue
        confs = [x["confidence"] for x in items if x["confidence"] is not None]
        titles = [x["title"] for x in items if x["title"]]
        themes.append(
            {
                "track": track,
                "signal_count": len(items),
                "avg_confidence": round(sum(confs) / max(1, len(confs)), 3),
                "top_keywords": top_keywords(titles),
                "sample_titles": titles[:5],
            }
        )

    themes.sort(key=lambda x: (x["avg_confidence"], x["signal_count"]), reverse=True)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_dir": str(VIP_DIR),
        "min_confidence": 0.35,
        "themes": themes,
    }


def main() -> None:
    payload = build_themes()
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] themes -> {OUT_PATH}")


if __name__ == "__main__":
    main()
