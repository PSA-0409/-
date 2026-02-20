"""Morning Scanner — US stock screener.

Generates three sections after each market session:
  - Gainers Top 15  (change >= +30%)
  - Day1 Target     (change +50%–+500%, turnover >= 200%, bullish candle)
  - Day2 Target     (yesterday's Day1 stocks, -30%–0% today, volume contraction)

Usage:
    python scanner.py                        # scan the most recent trading day
    python scanner.py --date 20260221        # historical back-test
    python scanner.py --dry-run              # no notifications, console output only
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Directory constants
# ---------------------------------------------------------------------------
DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
LOGS_DIR = Path("logs")

# US exchanges to include; OTC / Pink sheets are excluded by this allow-list
ALLOWED_EXCHANGES = {
    "NYSE",
    "NASDAQ",
    "AMEX",
    "NASDAQ GLOBAL SELECT",
    "NASDAQ GLOBAL MARKET",
    "NASDAQ CAPITAL MARKET",
    "NYSE AMERICAN",
    "NYSE ARCA",
}
FMP_EXCHANGE_SLUGS = ["nasdaq", "nyse", "amex"]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def setup_logging(date_str: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("scanner")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(
        LOGS_DIR / f"{date_str}_scanner.log", encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


# ---------------------------------------------------------------------------
# FMP API client
# ---------------------------------------------------------------------------


class FMPClient:
    """Financial Modeling Prep API client with exponential-backoff retry."""

    BASE_URL = "https://financialmodelingprep.com/api"

    def __init__(
        self,
        api_key: str,
        timeout: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self._logger = logging.getLogger("scanner")

    # ------------------------------------------------------------------
    # Low-level request with retry / back-off
    # ------------------------------------------------------------------

    def _request(
        self, endpoint: str, params: Optional[dict] = None
    ) -> list | dict:
        url = f"{self.BASE_URL}{endpoint}"
        p: dict = {"apikey": self.api_key, **(params or {})}

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.get(url, params=p, timeout=self.timeout)
                if resp.status_code in (429, 503):
                    wait = 2 ** attempt
                    self._logger.warning(
                        "API rate-limit (%s) — retrying in %ss (attempt %d/%d)",
                        resp.status_code,
                        wait,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    self._logger.debug(
                        "Request error, retrying in %ss: %s", wait, exc
                    )
                    time.sleep(wait)

        raise RuntimeError(
            f"FMP request failed after {self.max_retries} retries "
            f"({endpoint}): {last_exc}"
        )

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_exchange_quotes(self, exchange: str) -> list[dict]:
        """Return all quotes for one exchange slug (nasdaq/nyse/amex)."""
        data = self._request(f"/v3/quotes/{exchange}")
        return data if isinstance(data, list) else []

    def get_float(self, ticker: str) -> Optional[float]:
        """Return float shares for *ticker*, or None if unavailable."""
        try:
            data = self._request("/v4/shares_float", {"symbol": ticker})
            if isinstance(data, list) and data:
                val = data[0].get("floatShares")
                return float(val) if val is not None else None
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("%s: float取得失敗: %s", ticker, exc)
        return None

    def get_historical_prices(self, ticker: str, limit: int = 25) -> list[dict]:
        """Return the last *limit* daily bars (newest first)."""
        try:
            data = self._request(
                f"/v3/historical-price-full/{ticker}",
                {"timeseries": limit},
            )
            if isinstance(data, dict):
                return data.get("historical", [])
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("%s: historical取得失敗: %s", ticker, exc)
        return []

    def get_quote(self, ticker: str) -> Optional[dict]:
        """Return the current quote for *ticker*, or None."""
        try:
            data = self._request(f"/v3/quote/{ticker}")
            if isinstance(data, list) and data:
                return data[0]
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("%s: quote取得失敗: %s", ticker, exc)
        return None


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator != 0 else 0.0


def calc_avg_volume_20d(historical: list[dict]) -> float:
    """Average volume over the past 20 trading days (excluding today = index 0)."""
    past = historical[1:21]  # skip today; take next 20
    if not past:
        return 0.0
    vols = [float(d.get("volume") or 0) for d in past]
    return sum(vols) / len(vols)


def calc_rvol(today_volume: float, avg_vol: float) -> float:
    """RVOL = today_volume / avg_volume_20d."""
    return _safe_div(today_volume, avg_vol)


def calc_rotation(volume: float, float_shares: float) -> float:
    """Turnover rate (%) = volume / float_shares × 100."""
    return _safe_div(volume, float_shares) * 100.0


def calc_high_ratio(close: float, high: float) -> float:
    """High ratio (%) = close / high × 100."""
    return _safe_div(close, high) * 100.0


def _fmt_vol(vol: float) -> str:
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.1f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.0f}K"
    return f"{vol:.0f}"


def _fmt_mcap(mc: float) -> str:
    if mc >= 1_000_000_000:
        return f"${mc / 1_000_000_000:.2f}B"
    if mc >= 1_000_000:
        return f"${mc / 1_000_000:.1f}M"
    return f"${mc:,.0f}"


def _fmt_float(f: float) -> str:
    if f >= 1_000_000:
        return f"{f / 1_000_000:.1f}M"
    if f >= 1_000:
        return f"{f / 1_000:.0f}K"
    return f"{f:.0f}"


# ---------------------------------------------------------------------------
# Day1 data persistence
# ---------------------------------------------------------------------------


def save_day1_targets(targets: list[dict], date_str: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"day1_targets_{date_str}.json"
    path.write_text(
        json.dumps(targets, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logging.getLogger("scanner").info("Day1データ保存: %s", path)


def load_previous_day1_targets(
    target_date: str,
) -> tuple[list[dict], Optional[str]]:
    """
    Find the most recent day1_targets_*.json with a date *before* target_date.
    Returns (targets, date_str) or ([], None) when not found.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(DATA_DIR.glob("day1_targets_*.json"))
    logger = logging.getLogger("scanner")

    for f in reversed(files):
        parts = f.stem.split("_")  # ["day1", "targets", "YYYYMMDD"]
        if len(parts) < 3:
            continue
        file_date = parts[-1]
        if file_date < target_date:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                return data, file_date
            except Exception as exc:  # noqa: BLE001
                logger.error("Day1ファイル読込エラー %s: %s", f, exc)

    return [], None


# ---------------------------------------------------------------------------
# Screener helpers
# ---------------------------------------------------------------------------


def _collect_all_quotes(client: FMPClient, logger: logging.Logger) -> list[dict]:
    """Fetch quotes from all target exchanges, deduplicate by symbol."""
    all_quotes: list[dict] = []
    seen: set[str] = set()

    for slug in FMP_EXCHANGE_SLUGS:
        try:
            quotes = client.get_exchange_quotes(slug)
        except Exception as exc:  # noqa: BLE001
            logger.error("%s クオート取得エラー: %s", slug.upper(), exc)
            continue

        added = 0
        for q in quotes:
            symbol: str = q.get("symbol", "")
            if not symbol or symbol in seen:
                continue
            # Exclude ETFs
            if q.get("isEtf") is True:
                continue
            # Exclude OTC / unlisted
            ex = (q.get("exchange") or "").upper().strip()
            if ex and ex not in ALLOWED_EXCHANGES:
                continue
            seen.add(symbol)
            all_quotes.append(q)
            added += 1

        logger.info("%s: %d銘柄取得 (重複除去後)", slug.upper(), added)

    logger.info("全銘柄数（重複除去済）: %d", len(all_quotes))
    return all_quotes


def _parse_float_chg(q: dict) -> Optional[float]:
    """Extract changesPercentage from a quote dict, return None if invalid."""
    raw = q.get("changesPercentage") or q.get("changePercentage")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Gainers Top 15
# ---------------------------------------------------------------------------


def scan_gainers(
    all_quotes: list[dict], logger: logging.Logger
) -> list[dict]:
    """Return top-15 stocks with changesPercentage >= +30%, sorted descending."""
    gainers: list[dict] = []

    for q in all_quotes:
        chg = _parse_float_chg(q)
        if chg is None or chg < 30.0:
            continue

        price = float(q.get("price") or 0)
        if price <= 0:
            continue

        gainers.append(
            {
                "ticker": q.get("symbol", ""),
                "close": price,
                "change_pct": chg,
                "volume": float(q.get("volume") or 0),
                "market_cap": float(q.get("marketCap") or 0),
            }
        )

    gainers.sort(key=lambda x: x["change_pct"], reverse=True)
    top15 = gainers[:15]
    logger.info("Gainers Top 15: %d銘柄が +30%% 超え (上位15件を選択)", len(gainers))
    return top15


# ---------------------------------------------------------------------------
# Day1 Target
# ---------------------------------------------------------------------------


def scan_day1_targets(
    client: FMPClient,
    all_quotes: list[dict],
    logger: logging.Logger,
) -> list[dict]:
    """
    Filter stocks with change +50%–+500%, bullish candle, turnover >= 200%.
    Enriches each candidate with float data and 20-day average volume.
    """
    # ── First pass: basic price/change/candle filters (no extra API calls) ──
    candidates: list[dict] = []
    for q in all_quotes:
        chg = _parse_float_chg(q)
        if chg is None or not (50.0 <= chg <= 500.0):
            continue

        close = float(q.get("price") or 0)
        open_price = float(q.get("open") or 0)
        high = float(q.get("dayHigh") or 0)
        volume = float(q.get("volume") or 0)

        if close <= 0 or volume <= 0:
            continue
        # Bullish candle: close > open
        if close <= open_price:
            continue

        candidates.append(
            {
                "ticker": q.get("symbol", ""),
                "close": close,
                "open": open_price,
                "high": high,
                "change_pct": chg,
                "volume": volume,
            }
        )

    logger.info(
        "Day1候補（基本フィルタ後）: %d銘柄 — float/回転率検証を開始", len(candidates)
    )

    # ── Second pass: enrich with float + historical volume ──
    results: list[dict] = []
    for cand in candidates:
        ticker = cand["ticker"]
        try:
            float_shares = client.get_float(ticker)
            float_note: Optional[str] = None

            if float_shares is None:
                float_note = "【要確認】"
                logger.warning("%s: Float取得失敗 — 【要確認】フラグを付与", ticker)

            # 20-day average volume
            historical = client.get_historical_prices(ticker, limit=25)
            avg_vol_20d = calc_avg_volume_20d(historical)

            # Rotation check — skip only when float is *known* and < 200%
            rotation = 0.0
            if float_shares and float_shares > 0:
                rotation = calc_rotation(cand["volume"], float_shares)
                if rotation < 200.0:
                    logger.debug(
                        "%s: 回転率 %.1f%% < 200%% — スキップ", ticker, rotation
                    )
                    continue
            # float unknown → include with 【要確認】, rotation shown as 0

            rvol = calc_rvol(cand["volume"], avg_vol_20d) if avg_vol_20d > 0 else 0.0
            high_ratio = calc_high_ratio(cand["close"], cand["high"]) if cand["high"] > 0 else 0.0

            # Tags
            tags: list[str] = []
            if 2.0 <= cand["close"] <= 8.0:
                tags.append("$2-8")
            if float_shares is not None and 0 < float_shares <= 10_000_000:
                tags.append("SmallFloat")
            if rvol >= 5.0:
                tags.append("RVOL5+")
            if high_ratio >= 70.0:
                tags.append("NearHigh")

            results.append(
                {
                    "ticker": ticker,
                    "close": cand["close"],
                    "high": cand["high"],
                    "change_pct": cand["change_pct"],
                    "float": float_shares or 0.0,
                    "float_note": float_note,
                    "rvol": rvol,
                    "rotation": rotation,
                    "high_ratio": high_ratio,
                    "volume": cand["volume"],
                    "tags": tags,
                }
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: Day1処理エラー — スキップ: %s", ticker, exc)

    results.sort(key=lambda x: x["change_pct"], reverse=True)
    logger.info("Day1 Targets: %d銘柄", len(results))
    return results


# ---------------------------------------------------------------------------
# Day2 Target
# ---------------------------------------------------------------------------


def scan_day2_targets(
    client: FMPClient,
    day1_targets: list[dict],
    logger: logging.Logger,
) -> list[dict]:
    """
    For each yesterday-Day1 stock, check today's data for:
      -30% ≤ change ≤ 0%, Day2-high ≤ Day1-high,
      Day2-vol < Day1-vol, D2/D1-vol ≥ 4%.
    """
    results: list[dict] = []

    for d1 in day1_targets:
        ticker = d1.get("ticker", "")
        d1_volume = float(d1.get("volume") or 0)
        d1_high = float(d1.get("high") or 0)

        try:
            quote = client.get_quote(ticker)
            if not quote:
                logger.warning("%s: Day2 クオート取得失敗 — スキップ", ticker)
                continue

            d2_close = float(quote.get("price") or 0)
            d2_open = float(quote.get("open") or 0)
            d2_high = float(quote.get("dayHigh") or 0)
            d2_volume = float(quote.get("volume") or 0)
            prev_close = float(quote.get("previousClose") or 0)

            if prev_close <= 0 or d2_close <= 0:
                continue

            d2_chg = ((d2_close - prev_close) / prev_close) * 100.0

            # ── Filters ──
            if not (-30.0 <= d2_chg <= 0.0):
                continue
            if d1_high > 0 and d2_high > d1_high:
                continue
            if d1_volume > 0 and d2_volume >= d1_volume:
                continue

            d2d1_ratio = _safe_div(d2_volume, d1_volume) if d1_volume > 0 else 0.0
            if d2d1_ratio < 0.04:
                continue

            # Tags
            tags: list[str] = []
            if 0.04 <= d2d1_ratio <= 0.10:
                tags.append("D2/D1_Low")
            if d2_close > d2_open:
                tags.append("Green")

            d2_high_vs_d1_high = (
                _safe_div(d2_high, d1_high) * 100.0 if d1_high > 0 else 0.0
            )

            results.append(
                {
                    "ticker": ticker,
                    "d2_close": d2_close,
                    "d2_change_pct": d2_chg,
                    "d2d1_ratio": d2d1_ratio,
                    "d2_high": d2_high,
                    "d1_high": d1_high,
                    "d2_high_vs_d1_high": d2_high_vs_d1_high,
                    "tags": tags,
                }
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: Day2処理エラー — スキップ: %s", ticker, exc)

    logger.info("Day2 Targets: %d銘柄", len(results))
    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    gainers: list[dict],
    day1_targets: list[dict],
    day2_targets: list[dict],
    date_str: str,
    scan_time_et: str,
) -> str:
    date_fmt = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:8]}"
    sep = "━" * 40

    lines: list[str] = [
        f"📊 Morning Scan — {date_fmt}",
        "",
        sep,
        "◆ Gainers Top 15（+30%以上）",
        sep,
    ]

    if gainers:
        for i, g in enumerate(gainers, 1):
            lines.append(
                f"{i:2}. {g['ticker']:<8}  ${g['close']:.2f}"
                f"  +{g['change_pct']:.1f}%"
                f"  Vol:{_fmt_vol(g['volume'])}"
                f"  MCap:{_fmt_mcap(g['market_cap'])}"
            )
    else:
        lines.append("該当銘柄なし")

    lines += [
        "",
        sep,
        f"◆ Day1 Target（{len(day1_targets)}銘柄）",
        sep,
    ]

    if day1_targets:
        hdr = (
            f"{'Ticker':<8}  {'Close':>7}  {'Chg%':>8}  "
            f"{'Float':>8}  {'RVOL':>5}  {'Rotat%':>7}  {'High%':>6}  Tags"
        )
        lines.append(hdr)
        lines.append("-" * len(hdr))
        for d in day1_targets:
            float_str = (
                ("【要確認】" if d.get("float_note") else _fmt_float(d["float"]))
                if d["float"] > 0
                else "【要確認】"
            )
            tags_str = "".join(f"[{t}]" for t in d["tags"])
            lines.append(
                f"{d['ticker']:<8}  ${d['close']:>6.2f}  "
                f"{d['change_pct']:>+8.1f}%  "
                f"{float_str:>8}  "
                f"{d['rvol']:>5.1f}  "
                f"{d['rotation']:>7.1f}%  "
                f"{d['high_ratio']:>5.1f}%  "
                f"{tags_str}"
            )
    else:
        lines.append("該当銘柄なし")

    lines += [
        "",
        sep,
        f"◆ Day2 Target（{len(day2_targets)}銘柄）",
        sep,
    ]

    if day2_targets:
        hdr2 = (
            f"{'Ticker':<8}  {'D2Close':>8}  {'D2Chg%':>8}  "
            f"{'D2/D1Vol':>9}  {'D2H/D1H%':>9}  Tags"
        )
        lines.append(hdr2)
        lines.append("-" * len(hdr2))
        for d in day2_targets:
            tags_str = "".join(f"[{t}]" for t in d["tags"])
            lines.append(
                f"{d['ticker']:<8}  ${d['d2_close']:>7.2f}  "
                f"{d['d2_change_pct']:>+8.1f}%  "
                f"{d['d2d1_ratio']:>9.3f}  "
                f"{d['d2_high_vs_d1_high']:>8.1f}%  "
                f"{tags_str}"
            )
    else:
        lines.append("該当銘柄なし")

    lines += [
        "",
        f"実行時刻: {scan_time_et} ET | データ取得: FMP API",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _get_trading_date(arg_date: Optional[str]) -> str:
    """Return YYYYMMDD for the most recent trading day (or the given arg)."""
    if arg_date:
        return arg_date
    today = date.today()
    if today.weekday() == 5:   # Saturday → Friday
        today -= timedelta(days=1)
    elif today.weekday() == 6:  # Sunday → Friday
        today -= timedelta(days=2)
    return today.strftime("%Y%m%d")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Morning Stock Scanner — FMP-powered US equity screener"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        metavar="YYYYMMDD",
        help="Target date (default: most recent trading day)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip notifications; print report to stdout only",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    load_dotenv()
    args = _parse_args()

    date_str = _get_trading_date(args.date)
    logger = setup_logging(date_str)
    logger.info(
        "Morning Scanner 開始  date=%s  dry_run=%s", date_str, args.dry_run
    )

    fmp_key = os.getenv("FMP_API_KEY", "").strip()
    if not fmp_key:
        logger.error("[ERROR] FMP_API_KEY が設定されていません (.env を確認)")
        return 1

    client = FMPClient(fmp_key)

    # ── Fetch quotes ──────────────────────────────────────────────────────
    logger.info("全銘柄クオート取得中 (NYSE / NASDAQ / AMEX)…")
    all_quotes = _collect_all_quotes(client, logger)
    if not all_quotes:
        logger.error("[ERROR] クオートを取得できませんでした")
        return 1

    # ── Gainers ───────────────────────────────────────────────────────────
    logger.info("Gainers スキャン開始…")
    gainers = scan_gainers(all_quotes, logger)

    # ── Day1 ──────────────────────────────────────────────────────────────
    logger.info("Day1 Target スキャン開始…")
    day1_targets = scan_day1_targets(client, all_quotes, logger)

    # Persist Day1 for tomorrow's Day2 scan
    day1_save = [
        {
            "ticker": d["ticker"],
            "date": date_str,
            "close": d["close"],
            "high": d["high"],
            "volume": d["volume"],
            "float": d["float"],
            "tags": d["tags"],
        }
        for d in day1_targets
    ]
    save_day1_targets(day1_save, date_str)

    # ── Day2 ──────────────────────────────────────────────────────────────
    logger.info("Day2 Target スキャン開始…")
    prev_day1, prev_day1_date = load_previous_day1_targets(date_str)
    if not prev_day1:
        logger.warning(
            "前日のDay1データが見つかりません — Day2スキャンをスキップ"
        )
        day2_targets: list[dict] = []
    else:
        logger.info(
            "前日Day1データ読込完了  date=%s  %d銘柄", prev_day1_date, len(prev_day1)
        )
        day2_targets = scan_day2_targets(client, prev_day1, logger)

    # ── Report ────────────────────────────────────────────────────────────
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    # UTC-5 (EST) or UTC-4 (EDT) — use simple UTC-5 approximation
    from datetime import timedelta as _td

    et_offset = _td(hours=-5)
    now_et = (now_utc + et_offset).strftime("%H:%M")

    report = generate_report(gainers, day1_targets, day2_targets, date_str, now_et)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"{date_str}_morning_scan.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info("レポート保存: %s", report_path)

    # ── Notify ────────────────────────────────────────────────────────────
    if args.dry_run:
        logger.info("--dry-run: 通知スキップ")
        print(report)
    else:
        try:
            from notifier import send_notification

            send_notification(report, logger)
        except Exception as exc:  # noqa: BLE001
            logger.error("[ERROR] 通知エラー: %s", exc)

    logger.info("Morning Scanner 完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
