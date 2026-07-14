#!/usr/bin/env python3
"""
抓取质量体检脚本
统计每赛道文章数、平均置信度、噪音比例、缺料方向。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

VIP_DIR = Path(__file__).resolve().parent / "VIP_Txt_Dumps"
OUT = VIP_DIR / "vip_dump_health_report.json"

CONF_RE = re.compile(r"赛道置信度:\s*([0-9.]+)")
TRACK_RE = re.compile(r"^(?P<track>[A-Za-z0-9_]+)_Insights_\d{4}_\d{2}\.txt$")
NOISE_TERMS = [
    "cookie",
    "privacy policy",
    "terms of service",
    "all rights reserved",
    "subscribe",
    "market data and analysis",
]

TARGET_TRACKS = [
    "Innovative_Drugs",
    "AI_Compute_Core",
    "High_Speed_Interconnect",
    "Advanced_Substrates",
    "Humanoid_Robotics",
    "Low_Altitude_eVTOL",
    "Next_Gen_Storage",
    "Infrastructure_Risk_Control",
]


def split_blocks(text: str) -> List[str]:
    return [b.strip() for b in text.split("=" * 80) if b.strip()]


def main() -> None:
    by_track: Dict[str, Dict[str, float]] = defaultdict(lambda: {"count": 0, "conf_sum": 0.0, "noise_count": 0})

    for p in VIP_DIR.glob("*_Insights_*.txt"):
        m = TRACK_RE.match(p.name)
        if not m:
            continue
        track = m.group("track")
        text = p.read_text(encoding="utf-8", errors="ignore")
        blocks = split_blocks(text)
        for b in blocks:
            by_track[track]["count"] += 1
            c = CONF_RE.search(b)
            if c:
                by_track[track]["conf_sum"] += float(c.group(1))
            lb = b.lower()
            if sum(1 for t in NOISE_TERMS if t in lb) >= 2:
                by_track[track]["noise_count"] += 1

    tracks = []
    for track, s in sorted(by_track.items()):
        count = int(s["count"])
        avg_conf = (s["conf_sum"] / count) if count > 0 else 0.0
        noise_ratio = (s["noise_count"] / count) if count > 0 else 0.0
        tracks.append(
            {
                "track": track,
                "article_count": count,
                "avg_confidence": round(avg_conf, 3),
                "noise_ratio": round(noise_ratio, 3),
            }
        )

    existing = {t["track"] for t in tracks}
    missing_tracks = [t for t in TARGET_TRACKS if t not in existing]

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tracks": tracks,
        "missing_tracks": missing_tracks,
        "suggestion": "优先补齐 missing_tracks，每个方向至少15-20篇高置信样本。",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] health report -> {OUT}")


if __name__ == "__main__":
    main()
