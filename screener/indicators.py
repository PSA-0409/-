from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from screener.schemas import IndicatorSnapshot, IntradayLevels
from screener.utils import safe_div


@dataclass
class IntradayMetrics:
    vwap: Optional[float]
    vdu_ratio: Optional[float]
    range_ratio: Optional[float]
    levels: IntradayLevels


def compute_vwap(intraday: pd.DataFrame) -> Optional[float]:
    if intraday.empty:
        return None
    typical_price = (intraday["High"] + intraday["Low"] + intraday["Close"]) / 3
    volume = intraday["Volume"].fillna(0)
    total_volume = volume.sum()
    if total_volume == 0:
        return None
    return float((typical_price * volume).sum() / total_volume)


def compute_vdu(intraday: pd.DataFrame, interval: str) -> tuple[Optional[float], Optional[float]]:
    if intraday.empty:
        return None, None
    if interval == "1m":
        window = 20
    elif interval == "5m":
        window = 6
    else:
        window = max(1, min(len(intraday) // 4, 20))

    if len(intraday) < window * 2:
        return None, None
    volume = intraday["Volume"].fillna(0)
    early = volume.iloc[:window].mean()
    late = volume.iloc[-window:].mean()
    vdu_ratio = safe_div(late, early)

    range_early = float(intraday["High"].iloc[:window].max() - intraday["Low"].iloc[:window].min())
    range_late = float(intraday["High"].iloc[-window:].max() - intraday["Low"].iloc[-window:].min())
    range_ratio = safe_div(range_late, range_early) if range_early else None
    return vdu_ratio, range_ratio


def compute_levels(intraday: pd.DataFrame, interval: str) -> IntradayLevels:
    if intraday.empty:
        return IntradayLevels(None, None, None, None, None, None)
    session_high = float(intraday["High"].max())
    session_low = float(intraday["Low"].min())

    if interval == "1m":
        window = 60
    elif interval == "5m":
        window = 12
    else:
        window = min(12, len(intraday))

    last_window = intraday.iloc[-window:]
    range_upper = float(last_window["High"].max())
    range_lower = float(last_window["Low"].min())

    swing_low = _last_swing_low(intraday)
    return IntradayLevels(
        session_high=session_high,
        session_low=session_low,
        range_upper=range_upper,
        range_lower=range_lower,
        ignition_level_candidate=range_upper,
        first_pullback_low_candidate=swing_low,
    )


def _last_swing_low(intraday: pd.DataFrame) -> Optional[float]:
    lows = intraday["Low"].tolist()
    swing_lows = []
    for idx in range(1, len(lows) - 1):
        if lows[idx] < lows[idx - 1] and lows[idx] < lows[idx + 1]:
            swing_lows.append(lows[idx])
    if swing_lows:
        return float(swing_lows[-1])
    if lows:
        return float(min(lows))
    return None


def build_indicator_snapshot(
    today_volume: float,
    avg_volume: float,
    float_shares: Optional[float],
    intraday: pd.DataFrame,
    interval: str,
    spread_proxy: str,
) -> IndicatorSnapshot:
    rotation = safe_div(today_volume, float_shares) if float_shares else 0.0
    rvol = safe_div(today_volume, avg_volume) if avg_volume else 0.0
    vwap = compute_vwap(intraday)
    vdu_ratio, range_ratio = compute_vdu(intraday, interval)
    levels = compute_levels(intraday, interval)
    return IndicatorSnapshot(
        rotation=rotation,
        rvol=rvol,
        vwap=vwap,
        vdu_ratio=vdu_ratio,
        range_ratio=range_ratio,
        spread_proxy=spread_proxy,
        levels=levels,
    )
