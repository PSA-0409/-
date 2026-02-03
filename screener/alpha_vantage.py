from __future__ import annotations

import time
from typing import Optional, Tuple

import pandas as pd
import requests

from screener.schemas import FloatInfo, TickerSnapshot
from screener.utils import env_or_default, safe_div


class AlphaVantageClient:
    def __init__(self, timeout: float = 10.0, max_retries: int = 3, backoff: float = 1.5):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.base_url = "https://www.alphavantage.co/query"

    def _retry(self, func, *args, **kwargs):
        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(self.backoff * attempt)
        if last_exc:
            raise last_exc
        return None

    def _request(self, params: dict) -> dict:
        api_key = env_or_default("ALPHAVANTAGE_API_KEY", "")
        if not api_key:
            raise ValueError("ALPHAVANTAGE_API_KEYが設定されていません")
        params = {**params, "apikey": api_key}
        response = self._retry(lambda: requests.get(self.base_url, params=params, timeout=self.timeout))
        response.raise_for_status()
        data = response.json()
        if "Note" in data:
            raise RuntimeError("Alpha Vantage rate limit: " + data["Note"])
        if "Error Message" in data:
            raise RuntimeError(data["Error Message"])
        return data

    def fetch_snapshot(self, ticker: str, preferred_interval: str = "1min") -> Tuple[TickerSnapshot, pd.DataFrame]:
        overview = self._request({"function": "OVERVIEW", "symbol": ticker})
        quote = self._request({"function": "GLOBAL_QUOTE", "symbol": ticker})

        float_info = self._extract_float(overview, ticker)
        quote_data = (quote or {}).get("Global Quote", {})
        today_volume = float(quote_data.get("06. volume") or 0)
        price = float(quote_data.get("05. price") or 0)
        open_price = float(quote_data.get("02. open") or 0)
        high = float(quote_data.get("03. high") or 0)
        low = float(quote_data.get("04. low") or 0)
        previous_close = quote_data.get("08. previous close")

        intraday, interval, intraday_available = self._fetch_intraday(ticker, preferred_interval)
        avg_volume = self._average_volume(ticker)
        if today_volume == 0 and not intraday.empty:
            today_volume = float(intraday["Volume"].sum())

        snapshot = TickerSnapshot(
            ticker=ticker,
            float_info=float_info,
            today_volume=today_volume,
            avg_volume=avg_volume,
            price=price,
            open_price=open_price,
            high=high,
            low=low,
            previous_close=float(previous_close) if previous_close is not None else None,
            bid=None,
            ask=None,
            intraday_interval=interval,
            intraday_available=intraday_available,
        )
        return snapshot, intraday

    def _fetch_intraday(self, ticker: str, preferred_interval: str) -> Tuple[pd.DataFrame, str, bool]:
        intervals = [preferred_interval, "1min", "5min"]
        seen = set()
        ordered = []
        for interval in intervals:
            if interval in seen:
                continue
            seen.add(interval)
            ordered.append(interval)

        for interval in ordered:
            try:
                data = self._request(
                    {
                        "function": "TIME_SERIES_INTRADAY",
                        "symbol": ticker,
                        "interval": interval,
                        "outputsize": "compact",
                    }
                )
                key = f"Time Series ({interval})"
                series = data.get(key, {})
                if series:
                    df = self._series_to_df(series)
                    return df, interval, True
            except Exception:
                continue
        return self._fallback_daily(ticker)

    def _fallback_daily(self, ticker: str) -> Tuple[pd.DataFrame, str, bool]:
        data = self._request({"function": "TIME_SERIES_DAILY", "symbol": ticker, "outputsize": "compact"})
        series = data.get("Time Series (Daily)", {})
        if not series:
            return pd.DataFrame(), "1d", False
        df = self._series_to_df(series)
        return df, "1d", False

    def _series_to_df(self, series: dict) -> pd.DataFrame:
        rows = []
        for timestamp, values in series.items():
            rows.append(
                {
                    "Datetime": timestamp,
                    "Open": float(values.get("1. open") or 0),
                    "High": float(values.get("2. high") or 0),
                    "Low": float(values.get("3. low") or 0),
                    "Close": float(values.get("4. close") or 0),
                    "Volume": float(values.get("5. volume") or 0),
                }
            )
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df = df.sort_values("Datetime")
        df = df.dropna(subset=["High", "Low", "Close", "Volume"])
        return df

    def _average_volume(self, ticker: str) -> float:
        data = self._request({"function": "TIME_SERIES_DAILY", "symbol": ticker, "outputsize": "compact"})
        series = data.get("Time Series (Daily)", {})
        if not series:
            return 0.0
        volumes = [float(values.get("5. volume") or 0) for values in series.values()]
        if not volumes:
            return 0.0
        recent = volumes[:20]
        return float(sum(recent) / len(recent))

    def _extract_float(self, overview: dict, ticker: str) -> FloatInfo:
        shares_outstanding = overview.get("SharesOutstanding")
        if shares_outstanding:
            estimated = float(shares_outstanding) * 0.7
            rationale = f"{ticker} floatShares欠落のためSharesOutstandingの70%で推定"
            return FloatInfo(shares=estimated, estimated=True, rationale=rationale)
        market_cap = overview.get("MarketCapitalization")
        price = overview.get("52WeekHigh")
        if market_cap and price:
            estimated = safe_div(float(market_cap), float(price)) * 0.5
            rationale = f"{ticker} floatShares欠落のため時価総額/価格の50%で推定"
            return FloatInfo(shares=estimated, estimated=True, rationale=rationale)
        return FloatInfo(shares=None, estimated=True, rationale=f"{ticker} floatShares取得不可")
