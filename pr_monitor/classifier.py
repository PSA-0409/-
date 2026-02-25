"""PR重要度分類エンジン."""

from __future__ import annotations

import re

TIER1_KEYWORDS = [
    r"government contract",
    r"department of defense",
    r"\bdod\b",
    r"\bnasa\b",
    r"army|navy|air force|military",
    r"federal contract",
    r"billion.{0,20}contract",
    r"million.{0,20}contract",
    r"awarded.{0,30}contract",
    r"awarded.{0,30}grant",
    r"merger|acquisition|acquires|acquired",
    r"buyout|takeover",
    r"strategic combination",
    r"fda approval|fda approved|fda clearance",
    r"breakthrough designation",
    r"fast track designation",
    r"eua granted",
    r"\$\d+\s*billion",
    r"initial public offering|ipo",
    r"reverse stock split",
    r"going private",
    r"nasdaq compliance|nyse compliance",
    r"exclusive (license|partnership|agreement)",
    r"strategic partnership with",
]

TIER2_KEYWORDS = [
    r"quarterly results|q[1-4] \d{4} results|earnings",
    r"revenue guidance|full.year guidance|raises guidance",
    r"private placement|public offering|registered direct",
    r"shelf registration",
    r"collaboration agreement",
    r"license agreement",
    r"milestone payment",
    r"clinical trial results|phase [123] results",
    r"partnership",
    r"restructuring",
    r"ceo|cfo|president.{0,20}(appointed|resigned|named)",
]


def _match_patterns(patterns: list[str], text: str) -> list[str]:
    matched: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            matched.append(pattern)
    return matched


def classify_pr(title: str, body: str = "") -> dict:
    text = f"{title} {body}".lower()

    tier1 = _match_patterns(TIER1_KEYWORDS, text)
    if tier1:
        return {
            "tier": 1,
            "matched_keywords": tier1,
            "color": 0xFF0000,
            "emoji": "🔴",
            "label": "超重要",
            "ping": True,
        }

    tier2 = _match_patterns(TIER2_KEYWORDS, text)
    if tier2:
        return {
            "tier": 2,
            "matched_keywords": tier2,
            "color": 0xFFAA00,
            "emoji": "🟡",
            "label": "重要",
            "ping": False,
        }

    return {
        "tier": 3,
        "matched_keywords": [],
        "color": 0x808080,
        "emoji": "⚪",
        "label": "通常",
        "ping": False,
    }
