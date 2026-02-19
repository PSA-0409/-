"""report.py のルールベーススコアリング・レポート生成テスト。"""
from __future__ import annotations

from screener.report import _rotation_to_stage, score_ticker, build_report
from screener.schemas import LlmTickerPayload, FloatInfo


# ---------------------------------------------------------------------------
# テスト用フィクスチャ
# ---------------------------------------------------------------------------

def _make_payload(
    ticker="TEST",
    rotation=1.0,
    rvol=2.0,
    vwap=10.0,
    last_price=10.0,
    vdu_ratio=1.0,
    spread="0.0050",
    intraday_available=True,
    session_high=11.0,
    session_low=9.0,
    ignition=11.0,
    fpb=9.5,
    float_note=None,
) -> LlmTickerPayload:
    return LlmTickerPayload(
        ticker=ticker,
        float_shares=1_000_000,
        float_note=float_note,
        today_vol=500_000,
        avg_vol=300_000,
        rvol=rvol,
        rotation=rotation,
        vwap=vwap,
        vdu_ratio=vdu_ratio,
        range_ratio=1.0,
        last_price=last_price,
        day_high=11.0,
        day_low=9.0,
        open=9.5,
        previous_close=9.8,
        catalyst_summary="",
        dilution_flags="",
        spread_l2_notes=spread,
        session_high=session_high,
        session_low=session_low,
        range_upper=11.0,
        range_lower=9.0,
        ignition_level_candidate=ignition,
        first_pullback_low_candidate=fpb,
        intraday_interval="1m",
        intraday_available=intraday_available,
        data_notes="",
    )


# ---------------------------------------------------------------------------
# _rotation_to_stage のテスト
# ---------------------------------------------------------------------------

def test_stage_very_early():
    assert _rotation_to_stage(0.2) == 1

def test_stage_compression():
    assert _rotation_to_stage(0.5) == 2

def test_stage_ignition():
    assert _rotation_to_stage(1.2) == 4

def test_stage_distribution():
    assert _rotation_to_stage(4.0) == 7

def test_stage_collapse():
    assert _rotation_to_stage(10.0) == 9


# ---------------------------------------------------------------------------
# score_ticker のランク付けテスト
# ---------------------------------------------------------------------------

def test_rank_a_ideal():
    """Stage1-4 かつ Rotation 0.5-1.6 → ランクA"""
    p = _make_payload(rotation=1.0, rvol=3.0, intraday_available=True)
    s = score_ticker(p)
    assert s.rank == "A"
    assert s.stage == 3
    assert not s.deal_breakers


def test_rank_b_moderate():
    """Stage5、Rotation<2 → ランクB"""
    p = _make_payload(rotation=1.8, rvol=1.5, intraday_available=True)
    s = score_ticker(p)
    assert s.rank == "B"
    assert not s.deal_breakers


def test_rank_c_high_rotation():
    """Rotation>=3.0 → Deal-breaker → ランクC"""
    p = _make_payload(rotation=3.5, rvol=2.0, intraday_available=True)
    s = score_ticker(p)
    assert s.rank == "C"
    assert any("Rotation" in db for db in s.deal_breakers)


def test_rank_c_low_rvol():
    """RVOL<0.5 → Deal-breaker → ランクC"""
    p = _make_payload(rotation=0.8, rvol=0.3, intraday_available=True)
    s = score_ticker(p)
    assert s.rank == "C"
    assert any("RVOL" in db for db in s.deal_breakers)


def test_rank_c_no_intraday():
    """日中データなし → Deal-breaker → ランクC"""
    p = _make_payload(rotation=0.8, rvol=2.0, intraday_available=False)
    s = score_ticker(p)
    assert s.rank == "C"
    assert any("日中データ" in db for db in s.deal_breakers)


def test_note_price_above_vwap():
    """価格がVWAP+5%超 → ノート追加"""
    p = _make_payload(rotation=1.0, vwap=10.0, last_price=10.6)
    s = score_ticker(p)
    assert any("over-extended" in n for n in s.notes)


def test_note_vdu_accelerating():
    """VDU>1.5 → 出来高加速ノート"""
    p = _make_payload(rotation=1.0, vdu_ratio=2.0)
    s = score_ticker(p)
    assert any("加速" in n for n in s.notes)


def test_note_spread_unknown():
    """spread=unknown → ノート追加"""
    p = _make_payload(rotation=1.0, spread="unknown")
    s = score_ticker(p)
    assert any("スプレッド不明" in n for n in s.notes)


# ---------------------------------------------------------------------------
# build_report のテスト
# ---------------------------------------------------------------------------

def test_build_report_contains_sections():
    """レポートに必須セクションが含まれている"""
    payloads = [
        _make_payload("AAAA", rotation=1.0, rvol=3.0),
        _make_payload("BBBB", rotation=2.5, rvol=1.0),
        _make_payload("CCCC", rotation=4.0, rvol=0.5),
    ]
    report = build_report(payloads, top_n=5)
    assert "Top Candidates" in report
    assert "Lines to Watch" in report
    assert "Entry Allow" in report
    assert "Deal-breakers" in report
    assert "Summary" in report


def test_build_report_rank_a_appears_first():
    """ランクAティッカーがレポート上位に出る"""
    payloads = [
        _make_payload("GOOD", rotation=1.0, rvol=4.0),  # A
        _make_payload("BAD",  rotation=5.0, rvol=0.3),  # C
    ]
    report = build_report(payloads, top_n=5)
    assert report.index("GOOD") < report.index("BAD")


def test_build_report_no_candidates():
    """全てCランクでも Summary が出力される"""
    payloads = [
        _make_payload("ONLY", rotation=6.0, rvol=0.1, intraday_available=False),
    ]
    report = build_report(payloads, top_n=5)
    assert "Summary" in report
    assert "ONLY" in report


def test_build_report_top_n_limit():
    """top_n を超える候補は Top Candidates に出ない"""
    payloads = [_make_payload(f"T{i:02d}", rotation=0.5 + i * 0.1, rvol=3.0) for i in range(10)]
    report = build_report(payloads, top_n=3)
    # Top Candidates セクション（Lines to Watch より前）の候補数を確認
    top_section = report.split("### 👀")[0]
    # Rank A/B の行数が top_n 以下
    rank_lines = [l for l in top_section.splitlines() if l.startswith("**[Rank")]
    assert len(rank_lines) <= 3
