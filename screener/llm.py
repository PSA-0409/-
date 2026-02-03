from __future__ import annotations

import json
from typing import Iterable, Sequence

from openai import OpenAI

from screener.schemas import LlmTickerPayload
from screener.utils import env_or_default


SYSTEM_PROMPT = """
あなたは超小型フロート株のスクリーナー兼リスクマネージャーです。
目的: 早期のCompression→Ignition→Expansion候補を検出し、Retail Chase→Distribution→Collapseパターンを除外する。
ルール:
- 各ティッカーに対しStage 1-9を必ず1つ選ぶ。
- A/B/Cのランク付けを行う。
  - A: Stage1-4の初期＋Rotationが0.7〜1.4付近（または接近）でリスク許容。
  - B: Stage4-5、Rotation<2、分配兆候が弱い。
  - C: Stage7-9、Rotation>=3、希薄化リスク強い、またはスプレッド/流動性致命的。
- 欠損や推定値は「推定」と明記し、1行の根拠を書く。
- 出力順序を厳守:
  1) Top candidates (最大5件)
  2) Lines to watch
  3) Entry allow vs forbid
  4) Deal-breakers
  5) Summary (200-300文字の日本語)
- 価格はVWAP、レンジ、VDU比率、RangeRatio、Rotation、RVOL、希薄化・スプレッド・出来高を必ず参照する。
- data_notesに推定理由がある場合は必ず反映する。
""".strip()


def build_user_prompt(payloads: Sequence[LlmTickerPayload]) -> str:
    data = [payload.__dict__ for payload in payloads]
    return (
        "以下のJSON配列に基づいて判断してください。数値は必ず参照し、推定値は必ず\"推定\"と理由を明記。\n"
        + json.dumps(data, ensure_ascii=False)
    )


def call_llm(payloads: Iterable[LlmTickerPayload]) -> str:
    api_key = env_or_default("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEYが設定されていません")
    model = env_or_default("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(list(payloads))},
    ]
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=1200,
    )
    return response.choices[0].message.content.strip()
