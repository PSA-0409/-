"""FinnhubClient と spread_proxy の単体テスト。

外部APIは呼び出さず、モックで検証する。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from screener.finnhub_client import FinnhubClient
from screener.schemas import TickerSnapshot, FloatInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(bid=None, ask=None) -> TickerSnapshot:
    return TickerSnapshot(
        ticker="TEST",
        float_info=FloatInfo(shares=1_000_000, estimated=True, rationale="test"),
        today_volume=500_000,
        avg_volume=300_000,
        price=10.0,
        open_price=9.5,
        high=11.0,
        low=9.0,
        previous_close=9.8,
        bid=bid,
        ask=ask,
        intraday_interval="1m",
        intraday_available=True,
    )


def _sample_intraday() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Datetime": ["2024-01-01 10:00", "2024-01-01 10:01", "2024-01-01 10:02"],
            "Open":  [10.0, 10.5, 11.0],
            "High":  [10.5, 11.0, 11.5],
            "Low":   [ 9.5, 10.0, 10.5],
            "Close": [10.2, 10.8, 11.2],
            "Volume": [1000, 1500, 2000],
        }
    )


# ---------------------------------------------------------------------------
# spread_proxy のテスト
# ---------------------------------------------------------------------------

def test_spread_proxy_with_bid_ask():
    """bid/ask が両方ある場合は正確なスプレッドを返す。"""
    from screener.spread import compute_spread_proxy
    snapshot = _make_snapshot(bid=9.9, ask=10.1)
    result = compute_spread_proxy(snapshot)
    # mid=10.0, spread=0.2 → 0.2/10.0 = 0.0200
    assert result == "0.0200"


def test_spread_proxy_no_bid_ask_uses_bar_estimate():
    """bid/ask が None の場合、日中バーから推定スプレッドを返す。"""
    from screener.spread import compute_spread_proxy
    snapshot = _make_snapshot(bid=None, ask=None)
    intraday = _sample_intraday()
    result = compute_spread_proxy(snapshot, intraday)
    assert result.startswith("~")
    assert "(バー推定)" in result


def test_spread_proxy_no_bid_ask_no_intraday():
    """bid/ask も日中データも無い場合は 'unknown' を返す。"""
    from screener.spread import compute_spread_proxy
    snapshot = _make_snapshot(bid=None, ask=None)
    result = compute_spread_proxy(snapshot, None)
    assert result == "unknown"


def test_spread_proxy_empty_intraday():
    """空DataFrameは 'unknown' にフォールバックする。"""
    from screener.spread import compute_spread_proxy
    snapshot = _make_snapshot(bid=None, ask=None)
    result = compute_spread_proxy(snapshot, pd.DataFrame())
    assert result == "unknown"


# ---------------------------------------------------------------------------
# FinnhubClient._candle_to_df のテスト
# ---------------------------------------------------------------------------

def test_candle_to_df_normal():
    """正常なcandle レスポンスを DataFrame に変換できる。"""
    client = FinnhubClient()
    data = {
        "s": "ok",
        "t": [1700000000, 1700000060, 1700000120],
        "o": [10.0, 10.5, 11.0],
        "h": [10.5, 11.0, 11.5],
        "l": [9.5, 10.0, 10.5],
        "c": [10.2, 10.8, 11.2],
        "v": [1000, 1500, 2000],
    }
    df = client._candle_to_df(data)
    assert len(df) == 3
    assert list(df.columns) == ["Datetime", "Open", "High", "Low", "Close", "Volume"]
    assert df["High"].iloc[0] == 10.5


def test_candle_to_df_no_data():
    """s='no_data' の場合は空DataFrameを返す。"""
    client = FinnhubClient()
    df = client._candle_to_df({"s": "no_data"})
    assert df.empty


def test_candle_to_df_empty():
    """空dictの場合は空DataFrameを返す。"""
    client = FinnhubClient()
    df = client._candle_to_df({})
    assert df.empty


# ---------------------------------------------------------------------------
# FinnhubClient._fetch_float_info のテスト
# ---------------------------------------------------------------------------

def test_fetch_float_info_success():
    """shareOutstanding が取れた場合に FloatInfo を正しく作成する。"""
    client = FinnhubClient()
    mock_profile = {"shareOutstanding": 10.0}  # 10M shares

    with patch.object(client, "_get", return_value=mock_profile):
        info = client._fetch_float_info("TEST")

    assert info.estimated is True
    assert info.shares == pytest.approx(10_000_000 * 0.7)
    assert "70%" in info.rationale


def test_fetch_float_info_missing():
    """shareOutstanding が無い場合は shares=None を返す。"""
    client = FinnhubClient()
    with patch.object(client, "_get", return_value={}):
        info = client._fetch_float_info("TEST")

    assert info.shares is None
    assert info.estimated is True


def test_fetch_float_info_api_error():
    """API エラー時でも FloatInfo(shares=None) を返す（クラッシュしない）。"""
    client = FinnhubClient()
    with patch.object(client, "_get", side_effect=RuntimeError("API error")):
        info = client._fetch_float_info("TEST")

    assert info.shares is None


# ---------------------------------------------------------------------------
# FinnhubClient._average_volume のテスト
# ---------------------------------------------------------------------------

def test_average_volume_normal():
    """直近20バーの出来高平均を正しく計算する。"""
    client = FinnhubClient()
    mock_data = {"s": "ok", "v": [1000.0] * 25}  # 25バー、全て1000
    with patch.object(client, "_get", return_value=mock_data):
        avg = client._average_volume("TEST")
    assert avg == pytest.approx(1000.0)


def test_average_volume_empty():
    """出来高データが空の場合は 0.0 を返す。"""
    client = FinnhubClient()
    with patch.object(client, "_get", return_value={"s": "no_data", "v": []}):
        avg = client._average_volume("TEST")
    assert avg == 0.0


def test_average_volume_api_error():
    """API エラー時は 0.0 を返す（クラッシュしない）。"""
    client = FinnhubClient()
    with patch.object(client, "_get", side_effect=RuntimeError("error")):
        avg = client._average_volume("TEST")
    assert avg == 0.0
