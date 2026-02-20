"""PR Analyzer: keyword-based priority classification + OpenAI translation."""
from __future__ import annotations

import json
import re

from openai import OpenAI

from screener.utils import env_or_default

# ---------------------------------------------------------------------------
# Keyword-based priority rules (applied before LLM to fail-safe classify)
# ---------------------------------------------------------------------------

_CRITICAL_PATTERNS = [
    r"\$\s*\d[\d,.]*\s*[Bb]illion",
    r"\b(billion[- ]dollar)\b",
    r"\b(merger|acquisition|buyout|takeover)\b",
    r"\b(department\s+of\s+defense|DOD|U\.?S\.?\s+Army|U\.?S\.?\s+Navy|U\.?S\.?\s+Air\s+Force|Pentagon|DARPA|NASA)\b",
    r"\b(FDA\s+approval|FDA\s+cleared|FDA\s+authorized|breakthrough\s+therapy\s+designation)\b",
    r"\b(patent\s+grant|patent\s+issued|patent\s+awarded)\b",
]

_HIGH_PATTERNS = [
    r"\$\s*\d[\d,.]*\s*[Mm]illion",
    r"\b(million[- ]dollar)\b",
    r"\b(contract\s+award|awarded\s+(a\s+)?contract|government\s+contract|federal\s+contract|prime\s+contract)\b",
    r"\b(licensing\s+agreement|exclusive\s+license|royalty\s+agreement)\b",
    r"\b(partnership\s+agreement|strategic\s+partnership)\b",
    r"\b(letter\s+of\s+intent|memorandum\s+of\s+understanding|MOU|LOI)\b",
    r"\b(task\s+order|delivery\s+order|IDIQ)\b",
]


def classify_priority(title: str, summary: str) -> str:
    """Return ``'critical'``, ``'high'``, or ``'normal'`` via keyword matching."""
    text = title + " " + summary
    for pat in _CRITICAL_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return "critical"
    for pat in _HIGH_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return "high"
    return "normal"


# ---------------------------------------------------------------------------
# LLM-based translation + classification
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """あなたは米国株のプレスリリース（PR）翻訳・分類アシスタントです。
入力された英語のタイトルと概要を日本語に翻訳し、以下のJSONフォーマットのみで返してください。余分な文字は一切不要です。

{
  "title_ja": "翻訳タイトル（簡潔に）",
  "summary_ja": "翻訳概要（200文字以内）",
  "priority": "critical|high|normal",
  "key_figures": "主要数値・金額・契約規模（なければ空文字）"
}

priority判定基準:
- critical: 数十億ドル規模の契約、M&A・買収・合併、政府/国防省/NASA/DARPA契約、FDA承認
- high: 数百万ドル規模の契約、政府契約、ライセンス・MOU・LOI・戦略的提携
- normal: 上記以外の一般的なIR/お知らせ"""


def translate_and_classify(title: str, summary: str) -> dict:
    """Call OpenAI to translate English PR title+summary to Japanese and classify priority.

    Returns dict with keys: title_ja, summary_ja, priority, key_figures.
    Falls back gracefully if the API call fails.
    """
    api_key = env_or_default("OPENAI_API_KEY", "")
    if not api_key:
        return {
            "title_ja": title,
            "summary_ja": summary,
            "priority": classify_priority(title, summary),
            "key_figures": "",
        }

    model = env_or_default("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    user_content = f"タイトル: {title}\n\n概要: {summary[:800]}"

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
        max_tokens=500,
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content.strip()
    result = json.loads(content)

    # Ensure all expected keys exist
    return {
        "title_ja": result.get("title_ja", title),
        "summary_ja": result.get("summary_ja", summary),
        "priority": result.get("priority", classify_priority(title, summary)),
        "key_figures": result.get("key_figures", ""),
    }
