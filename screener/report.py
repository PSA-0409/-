"""ルールベースのスコアリングとレポート生成。

OpenAI不要・完全無料で動作する。
LLMプロンプトで定義されていたロジック（Stage / ランク / Deal-breaker）を
Pythonのルールとして実装する。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List

from screener.schemas import LlmTickerPayload


# ---------------------------------------------------------------------------
# スコアリング定数
# ---------------------------------------------------------------------------

# Rotationのステージ境界（LLMプロンプトの定義を踏襲）
_ROTATION_STAGE: list[tuple[float, int]] = [
    (0.3,  1),   # 極初期
    (0.7,  2),   # Compression初期
    (1.0,  3),   # Compression後期
    (1.4,  4),   # Ignition候補
    (2.0,  5),   # Expansion初期
    (3.0,  6),   # Expansion後期
    (5.0,  7),   # Distribution
    (8.0,  8),   # Collapse初期
]
_STAGE_MAX = 9  # Collapse後期


def _rotation_to_stage(rotation: float) -> int:
    for threshold, stage in _ROTATION_STAGE:
        if rotation <= threshold:
            return stage
    return _STAGE_MAX


@dataclass
class ScoredTicker:
    payload: LlmTickerPayload
    stage: int
    rank: str           # A / B / C / X
    score: float        # 高いほど良い（ランキング用）
    deal_breakers: list[str]
    notes: list[str]


# ---------------------------------------------------------------------------
# メインのスコアリング関数
# ---------------------------------------------------------------------------

def score_ticker(payload: LlmTickerPayload) -> ScoredTicker:
    """1ティッカーをルールベースでスコアリングしてScoredTickerを返す。"""
    stage = _rotation_to_stage(payload.rotation)
    deal_breakers: list[str] = []
    notes: list[str] = []

    # --- Deal-breaker チェック ---
    if payload.rotation >= 3.0:
        deal_breakers.append(f"Rotation={payload.rotation:.2f} (>=3.0 分配/崩壊リスク)")
    if payload.rvol is not None and payload.rvol < 0.5:
        deal_breakers.append(f"RVOL={payload.rvol:.2f} (<0.5 出来高不足)")
    if not payload.intraday_available:
        deal_breakers.append("日中データ不足（推定値のみ）")
    if payload.spread_l2_notes == "unknown":
        notes.append("スプレッド不明（流動性要注意）")
    if payload.float_note:
        notes.append(f"Float推定: {payload.float_note}")

    # --- VWAP位置チェック ---
    if payload.vwap and payload.last_price:
        if payload.last_price > payload.vwap * 1.05:
            notes.append(f"価格がVWAP+5%超 (over-extended注意)")
        elif payload.last_price < payload.vwap * 0.95:
            notes.append(f"価格がVWAP-5%未満 (弱い)")

    # --- VDU比率チェック ---
    if payload.vdu_ratio is not None:
        if payload.vdu_ratio > 1.5:
            notes.append(f"VDU={payload.vdu_ratio:.2f} (出来高加速中)")
        elif payload.vdu_ratio < 0.5:
            notes.append(f"VDU={payload.vdu_ratio:.2f} (出来高失速)")

    # --- ランク付け ---
    if deal_breakers:
        rank = "C"
    elif stage <= 4 and 0.5 <= payload.rotation <= 1.6:
        rank = "A"
    elif stage <= 5 and payload.rotation < 2.0:
        rank = "B"
    else:
        rank = "C"

    # --- スコア計算（ランキング用）---
    # 低いRotation・高いRVOL・Stage 2-4 を高得点とする
    score = 0.0
    if rank == "A":
        score += 100.0
    elif rank == "B":
        score += 50.0

    # RVOL ボーナス（高いほど良い、ただし上限あり）
    if payload.rvol is not None:
        score += min(payload.rvol, 5.0) * 10

    # Rotation ペナルティ（高いほど悪い）
    score -= payload.rotation * 5

    # VDU ボーナス
    if payload.vdu_ratio is not None:
        score += min(payload.vdu_ratio, 3.0) * 5

    # Deal-breaker ペナルティ
    score -= len(deal_breakers) * 30

    return ScoredTicker(
        payload=payload,
        stage=stage,
        rank=rank,
        score=score,
        deal_breakers=deal_breakers,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# レポート生成
# ---------------------------------------------------------------------------

def build_report(payloads: list[LlmTickerPayload], top_n: int = 5) -> str:
    """全ティッカーをスコアリングしてMarkdownレポートを生成する。"""
    scored = [score_ticker(p) for p in payloads]
    scored.sort(key=lambda s: s.score, reverse=True)

    candidates = [s for s in scored if s.rank in ("A", "B")]
    others = [s for s in scored if s.rank == "C"]

    lines: list[str] = []

    # --- ヘッダー ---
    lines.append("## 📊 Micro-Float Screener レポート")
    lines.append("")

    # --- Top Candidates ---
    lines.append("### 🎯 Top Candidates")
    if candidates:
        for s in candidates[:top_n]:
            p = s.payload
            vwap_str = f"{p.vwap:.2f}" if p.vwap else "N/A"
            rvol_str = f"{p.rvol:.2f}" if p.rvol is not None else "N/A"
            vdu_str  = f"{p.vdu_ratio:.2f}" if p.vdu_ratio is not None else "N/A"
            lines.append(
                f"**[Rank {s.rank} / Stage {s.stage}] {p.ticker}** "
                f"| 価格: ${p.last_price:.2f} "
                f"| RVOL: {rvol_str} "
                f"| Rotation: {p.rotation:.2f} "
                f"| VWAP: ${vwap_str} "
                f"| VDU: {vdu_str} "
                f"| Spread: {p.spread_l2_notes}"
            )
            for note in s.notes:
                lines.append(f"  - 📝 {note}")
            lines.append("")
    else:
        lines.append("_有効な候補なし_")
        lines.append("")

    # --- Lines to Watch ---
    lines.append("### 👀 Lines to Watch")
    for s in candidates[:top_n]:
        p = s.payload
        hi = f"{p.session_high:.2f}" if p.session_high else "N/A"
        lo = f"{p.session_low:.2f}" if p.session_low else "N/A"
        ign = f"{p.ignition_level_candidate:.2f}" if p.ignition_level_candidate else "N/A"
        fpb = f"{p.first_pullback_low_candidate:.2f}" if p.first_pullback_low_candidate else "N/A"
        lines.append(
            f"**{p.ticker}**: セッションH/L ${hi}/${lo} "
            f"| Ignition候補 ${ign} "
            f"| 初押しサポート ${fpb}"
        )
    if not candidates:
        lines.append("_候補なし_")
    lines.append("")

    # --- Entry Allow vs Forbid ---
    lines.append("### ✅ Entry Allow / ❌ Forbid")
    allow = [s for s in candidates if s.rank == "A"]
    forbid = others + [s for s in candidates if s.rank == "B" and s.deal_breakers]

    if allow:
        lines.append("**Allow:**")
        for s in allow[:top_n]:
            lines.append(f"  - {s.payload.ticker} (Stage {s.stage}, Rotation {s.payload.rotation:.2f})")
    else:
        lines.append("**Allow:** なし")

    if forbid:
        lines.append("**Forbid:**")
        for s in forbid[:5]:
            reason = s.deal_breakers[0] if s.deal_breakers else "Rank C"
            lines.append(f"  - {s.payload.ticker}: {reason}")
    lines.append("")

    # --- Deal-breakers ---
    lines.append("### 🚫 Deal-breakers")
    has_db = False
    for s in scored:
        if s.deal_breakers:
            has_db = True
            lines.append(f"**{s.payload.ticker}**:")
            for db in s.deal_breakers:
                lines.append(f"  - {db}")
    if not has_db:
        lines.append("_Deal-breakerなし_")
    lines.append("")

    # --- Summary ---
    lines.append("### 📝 Summary")
    a_tickers = [s.payload.ticker for s in scored if s.rank == "A"]
    b_tickers = [s.payload.ticker for s in scored if s.rank == "B"]
    c_tickers = [s.payload.ticker for s in scored if s.rank == "C"]
    total = len(scored)
    lines.append(
        f"対象{total}銘柄: ランクA={len(a_tickers)}件 / B={len(b_tickers)}件 / C={len(c_tickers)}件。"
    )
    if a_tickers:
        lines.append(f"注目候補: {', '.join(a_tickers[:5])}。")
    if b_tickers:
        lines.append(f"監視: {', '.join(b_tickers[:5])}。")
    if c_tickers:
        lines.append(f"除外: {', '.join(c_tickers[:5])}。")

    return "\n".join(lines)
