import pandas as pd

from screener.indicators import compute_vdu, compute_vwap


def sample_intraday():
    data = {
        "High": [10, 11, 12, 11, 10, 9, 9, 10, 10, 11, 12, 11],
        "Low": [9, 10, 11, 10, 9, 8, 8, 9, 9, 10, 11, 10],
        "Close": [9.5, 10.5, 11.5, 10.5, 9.5, 8.5, 8.5, 9.5, 9.5, 10.5, 11.5, 10.5],
        "Volume": [100, 100, 100, 100, 200, 200, 200, 200, 100, 100, 100, 100],
    }
    return pd.DataFrame(data)


def test_compute_vwap():
    df = sample_intraday()
    vwap = compute_vwap(df)
    assert round(vwap, 4) == 9.75  # typical=(H+L+C)/3 の出来高加重平均


def test_compute_vdu_range_ratio():
    df = sample_intraday()
    vdu_ratio, range_ratio = compute_vdu(df, "1m")
    assert vdu_ratio is None
    assert range_ratio is None

    vdu_ratio, range_ratio = compute_vdu(df, "5m")
    assert vdu_ratio is not None
    assert range_ratio is not None
    assert round(vdu_ratio, 2) == 1.0
