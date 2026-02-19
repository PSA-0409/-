from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import pandas as pd
import requests

from screener.schemas import FloatInfo, TickerSnapshot
from screener.utils import env_or_default, safe_div

_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubClient:
    """Finnhub REST APIクライアント。

    Alpha Vantageクライアントと同一のインターフェース(fetch_snapshot)を提供し、
    以下の改善を実現します:
    - floatShares: shareOutstanding から推定（精度向上、70%固定ではなく明示）
    - bid / ask: quote エンドポイントから実値取得
    - レート制限: 無料枠60req/分（Alpha Vantageの12倍）
    - intraday: stock/candle エンドポイント（1min/5min対応）
    """

    def __init__(self, timeout: float = 10.0, max_retries: int = 3, backoff: float = 1.5):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff

    def _api_key(self) -> str:
        key = env_or_default("FINNHUB_API_KEY", "")
        if not key:
            raise ValueError("FINNHUB_API_KEYが設定されていません")
        return key

    def _get(self, path: str, params: dict) -> dict:
        """リトライ付きGETリクエスト。"""
        url = f"{_BASE_URL}{path}"
        params = {**params, "token": self._api_key()}
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                # Finnhub はエラー時に {"error": "..."} を返すことがある
                if isinstance(data, dict) and "error" in data:
                    raise RuntimeError(f"Finnhub API エラー: {data['error']}")
                return data
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(self.backoff * attempt)
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Public interface (alpha_vantage.AlphaVantageClient と同一シグネチャ)
    # ------------------------------------------------------------------

    def fetch_snapshot(
        self, ticker: str, preferred_interval: str = "1m"
    ) -> Tuple[TickerSnapshot, pd.DataFrame]:
        """ティッカーのスナップショットと日中データを取得する。"""
        quote = self._fetch_quote(ticker)
        float_info = self._fetch_float_info(ticker)
        intraday, interval, intraday_available = self._fetch_intraday(ticker, preferred_interval)
        avg_volume = self._average_volume(ticker)

        # quote フィールドのマッピング
        price = float(quote.get("c") or 0)           # current price
        open_price = float(quote.get("o") or 0)       # open
        high = float(quote.get("h") or 0)             # high
        low = float(quote.get("l") or 0)              # low
        previous_close = quote.get("pc")              # previous close
        today_volume = float(quote.get("v") or 0)
        bid = quote.get("bid") or None
        ask = quote.get("ask") or None

        # 日中データから today_volume を補完
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_quote(self, ticker: str) -> dict:
        """Quote + bid/ask を取得する。

        Finnhub の /quote エンドポイントは bid/ask を含まないため、
        /stock/bidask エンドポイントで補完する。
        """
        quote = self._get("/quote", {"symbol": ticker})

        # bid/ask の補完 (失敗しても握りつぶす)
        try:
            bidask = self._get("/stock/bidask", {"symbol": ticker})
            quote["bid"] = bidask.get("b")
            quote["ask"] = bidask.get("a")
        except Exception:  # noqa: BLE001
            quote["bid"] = None
            quote["ask"] = None

        return quote

    def _fetch_float_info(self, ticker: str) -> FloatInfo:
        """Company Profile 2（無料）から株式数を取得しfloatを推定する。"""
        try:
            profile = self._get("/stock/profile2", {"symbol": ticker})
            shares_outstanding = profile.get("shareOutstanding")
            if shares_outstanding and float(shares_outstanding) > 0:
                # shareOutstanding は百万株単位で返ってくる
                shares_mil = float(shares_outstanding) * 1_000_000
                estimated = shares_mil * 0.7
                rationale = (
                    f"{ticker} floatShares欠落のためshareOutstanding({shares_outstanding:.2f}M)"
                    f"の70%で推定"
                )
                return FloatInfo(shares=estimated, estimated=True, rationale=rationale)
        except Exception:  # noqa: BLE001
            pass
        return FloatInfo(
            shares=None, estimated=True, rationale=f"{ticker} floatShares取得不可"
        )

    def _fetch_intraday(
        self, ticker: str, preferred_interval: str
    ) -> Tuple[pd.DataFrame, str, bool]:
        """日中ローソク足を取得する。

        Finnhub /stock/candle の resolution:
          1  → 1分足
          5  → 5分足
          D  → 日足
        """
        interval_map = {"1m": "1", "1min": "1", "5m": "5", "5min": "5"}

        # 優先インターバルから順に試す
        candidates = [preferred_interval, "1m", "5m"]
        seen: set[str] = set()
        ordered = []
        for iv in candidates:
            key = interval_map.get(iv, iv)
            if key not in seen:
                seen.add(key)
                ordered.append(key)

        now_ts = int(datetime.now(timezone.utc).timestamp())
        from_ts = now_ts - 60 * 60 * 8  # 直近8時間

        for resolution in ordered:
            try:
                data = self._get(
                    "/stock/candle",
                    {
                        "symbol": ticker,
                        "resolution": resolution,
                        "from": from_ts,
                        "to": now_ts,
                    },
                )
                df = self._candle_to_df(data)
                if not df.empty:
                    label = "1m" if resolution == "1" else "5m" if resolution == "5" else resolution
                    return df, label, True
            except Exception:  # noqa: BLE001
                continue

        # フォールバック: 日足
        return self._fallback_daily(ticker)

    def _fallback_daily(self, ticker: str) -> Tuple[pd.DataFrame, str, bool]:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        from_ts = now_ts - 60 * 60 * 24 * 30  # 直近30日
        try:
            data = self._get(
                "/stock/candle",
                {"symbol": ticker, "resolution": "D", "from": from_ts, "to": now_ts},
            )
            df = self._candle_to_df(data)
            return df, "1d", False
        except Exception:  # noqa: BLE001
            return pd.DataFrame(), "1d", False

    def _candle_to_df(self, data: dict) -> pd.DataFrame:
        """Finnhub candle レスポンスをDataFrameに変換する。"""
        if not data or data.get("s") == "no_data":
            return pd.DataFrame()

        timestamps = data.get("t", [])
        opens = data.get("o", [])
        highs = data.get("h", [])
        lows = data.get("l", [])
        closes = data.get("c", [])
        volumes = data.get("v", [])

        if not timestamps:
            return pd.DataFrame()

        rows = []
        for i, ts in enumerate(timestamps):
            rows.append(
                {
                    "Datetime": datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "Open": float(opens[i]) if i < len(opens) else 0.0,
                    "High": float(highs[i]) if i < len(highs) else 0.0,
                    "Low": float(lows[i]) if i < len(lows) else 0.0,
                    "Close": float(closes[i]) if i < len(closes) else 0.0,
                    "Volume": float(volumes[i]) if i < len(volumes) else 0.0,
                }
            )

        df = pd.DataFrame(rows)
        df = df.sort_values("Datetime").reset_index(drop=True)
        df = df.dropna(subset=["High", "Low", "Close", "Volume"])
        return df

    def _average_volume(self, ticker: str) -> float:
        """直近20日の平均出来高を算出する。"""
        now_ts = int(datetime.now(timezone.utc).timestamp())
        from_ts = now_ts - 60 * 60 * 24 * 30
        try:
            data = self._get(
                "/stock/candle",
                {"symbol": ticker, "resolution": "D", "from": from_ts, "to": now_ts},
            )
            volumes = data.get("v", [])
            if not volumes:
                return 0.0
            recent = [float(v) for v in volumes[-20:]]
            return float(sum(recent) / len(recent)) if recent else 0.0
        except Exception:  # noqa: BLE001
            return 0.0
