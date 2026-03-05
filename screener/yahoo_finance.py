from __future__ import annotations

import time
from typing import Optional, Tuple

import pandas as pd
import yfinance as yf

from screener.schemas import FloatInfo, TickerSnapshot
from screener.utils import safe_div


class YahooFinanceClient:
    def __init__(self, max_retries: int = 3, backoff: float = 1.5):
        self.max_retries = max_retries
        self.backoff = backoff

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

    def fetch_snapshot(self, ticker: str, preferred_interval: str = "1m") -> Tuple[TickerSnapshot, pd.DataFrame]:
        tkr = yf.Ticker(ticker)
        info = self._retry(lambda: tkr.info) or {}

        float_info = self._extract_float(info, ticker)

        price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        open_price = float(info.get("open") or info.get("regularMarketOpen") or 0)
        high = float(info.get("dayHigh") or info.get("regularMarketDayHigh") or 0)
        low = float(info.get("dayLow") or info.get("regularMarketDayLow") or 0)
        today_volume = float(info.get("volume") or info.get("regularMarketVolume") or 0)
        avg_volume = float(info.get("averageVolume") or info.get("averageDailyVolume10Day") or 0)
        previous_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
        bid = info.get("bid")
        ask = info.get("ask")

        intraday, interval, intraday_available = self._fetch_intraday(tkr, preferred_interval)

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
            bid=float(bid) if bid is not None else None,
            ask=float(ask) if ask is not None else None,
            intraday_interval=interval,
            intraday_available=intraday_available,
        )
        return snapshot, intraday

    def _fetch_intraday(self, tkr: yf.Ticker, preferred_interval: str) -> Tuple[pd.DataFrame, str, bool]:
        intervals = [preferred_interval, "1m", "5m"]
        seen: set[str] = set()
        ordered: list[str] = []
        for interval in intervals:
            if interval in seen:
                continue
            seen.add(interval)
            ordered.append(interval)

        for interval in ordered:
            try:
                df = self._retry(lambda i=interval: tkr.history(period="1d", interval=i))
                if df is not None and not df.empty:
                    return self._normalize_df(df), interval, True
            except Exception:  # noqa: BLE001
                continue
        return self._fallback_daily(tkr)

    def _fallback_daily(self, tkr: yf.Ticker) -> Tuple[pd.DataFrame, str, bool]:
        try:
            df = self._retry(lambda: tkr.history(period="20d", interval="1d"))
            if df is not None and not df.empty:
                return self._normalize_df(df), "1d", False
        except Exception:  # noqa: BLE001
            pass
        return pd.DataFrame(), "1d", False

    def _normalize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy().reset_index()
        # yfinance uses "Datetime" for intraday, "Date" for daily
        if "Datetime" not in df.columns and "Date" in df.columns:
            df = df.rename(columns={"Date": "Datetime"})
        df = df[["Datetime", "Open", "High", "Low", "Close", "Volume"]].copy()
        df = df.dropna(subset=["High", "Low", "Close", "Volume"])
        df = df.sort_values("Datetime").reset_index(drop=True)
        return df

    def _extract_float(self, info: dict, ticker: str) -> FloatInfo:
        float_shares = info.get("floatShares")
        if float_shares:
            return FloatInfo(shares=float(float_shares), estimated=False, rationale=None)
        shares_outstanding = info.get("sharesOutstanding")
        if shares_outstanding:
            estimated = float(shares_outstanding) * 0.7
            rationale = f"{ticker} floatShares欠落のためSharesOutstandingの70%で推定"
            return FloatInfo(shares=estimated, estimated=True, rationale=rationale)
        market_cap = info.get("marketCap")
        high52w = info.get("fiftyTwoWeekHigh")
        if market_cap and high52w:
            estimated = safe_div(float(market_cap), float(high52w)) * 0.5
            rationale = f"{ticker} floatShares欠落のため時価総額/価格の50%で推定"
            return FloatInfo(shares=estimated, estimated=True, rationale=rationale)
        return FloatInfo(shares=None, estimated=True, rationale=f"{ticker} floatShares取得不可")
