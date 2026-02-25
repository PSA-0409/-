"""FMP API経由で株価・時価総額・浮動株を取得."""

from __future__ import annotations

from typing import Optional

import requests


class MarketDataFetcher:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://financialmodelingprep.com/api/v3"

    def get_quote(self, ticker: str) -> Optional[dict]:
        url = f"{self.base_url}/quote/{ticker}?apikey={self.api_key}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if not data:
                return None
            q = data[0]
            return {
                "price": q.get("price"),
                "change_pct": q.get("changesPercentage"),
                "market_cap": q.get("marketCap"),
                "volume": q.get("volume"),
                "avg_volume": q.get("avgVolume"),
            }
        except Exception:
            return None

    def get_shares_info(self, ticker: str) -> Optional[dict]:
        url = f"{self.base_url}/shares_float?symbol={ticker}&apikey={self.api_key}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if not data:
                return None
            s = data[0]
            return {
                "float_shares": s.get("floatShares"),
                "outstanding_shares": s.get("outstandingShares"),
                "free_float_pct": s.get("freeFloat"),
            }
        except Exception:
            return None

    def is_penny_stock(self, market_cap: Optional[float], penny_threshold: float) -> bool:
        if market_cap is None:
            return True
        return market_cap < penny_threshold

    @staticmethod
    def format_money(value: Optional[float]) -> str:
        if value is None:
            return "N/A"
        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        if value >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"${value / 1_000:.0f}K"
        return f"${value:.2f}"

    @staticmethod
    def format_shares(value: Optional[float]) -> str:
        if value is None:
            return "N/A"
        if value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}B株"
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M株"
        return f"{value:,.0f}株"
