from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class FloatInfo:
    shares: Optional[float]
    estimated: bool
    rationale: Optional[str]


@dataclass
class TickerSnapshot:
    ticker: str
    float_info: FloatInfo
    today_volume: float
    avg_volume: float
    price: float
    open_price: float
    high: float
    low: float
    previous_close: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    intraday_interval: str
    intraday_available: bool


@dataclass
class IntradayLevels:
    session_high: Optional[float]
    session_low: Optional[float]
    range_upper: Optional[float]
    range_lower: Optional[float]
    ignition_level_candidate: Optional[float]
    first_pullback_low_candidate: Optional[float]


@dataclass
class IndicatorSnapshot:
    rotation: float
    rvol: float
    vwap: Optional[float]
    vdu_ratio: Optional[float]
    range_ratio: Optional[float]
    spread_proxy: str
    levels: IntradayLevels


@dataclass
class LlmTickerPayload:
    ticker: str
    float_shares: Optional[float]
    float_note: Optional[str]
    today_vol: float
    avg_vol: float
    rvol: float
    rotation: float
    vwap: Optional[float]
    vdu_ratio: Optional[float]
    range_ratio: Optional[float]
    last_price: float
    day_high: float
    day_low: float
    open: float
    previous_close: Optional[float]
    catalyst_summary: str
    dilution_flags: str
    spread_l2_notes: str
    session_high: Optional[float]
    session_low: Optional[float]
    range_upper: Optional[float]
    range_lower: Optional[float]
    ignition_level_candidate: Optional[float]
    first_pullback_low_candidate: Optional[float]
    intraday_interval: str
    intraday_available: bool
    data_notes: str
