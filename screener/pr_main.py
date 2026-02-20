"""PR通知Bot — メインエントリポイント.

Usage:
    python -m screener.pr_main --tickers AAPL,TSLA --interval 300
    python -m screener.pr_main --tickers AAPL      --once
    python -m screener.pr_main                     # tickers.txt から読み込み
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from screener.alpha_vantage import AlphaVantageClient
from screener.pr_analyzer import classify_priority, translate_and_classify
from screener.pr_monitor import poll_new_prs
from screener.pr_notify import send_pr_notification
from screener.utils import read_tickers, setup_logger

load_dotenv()

logger = setup_logger("pr_bot")


# ---------------------------------------------------------------------------
# Market data helper
# ---------------------------------------------------------------------------

def _fetch_market_info(
    ticker: str, av: AlphaVantageClient
) -> tuple[Optional[float], Optional[float]]:
    """Return (float_shares, market_cap) from Alpha Vantage OVERVIEW.

    Both values may be None if the API call fails or data is missing.
    Float shares are estimated as 70% of SharesOutstanding (same heuristic
    used elsewhere in this codebase).
    """
    try:
        # AlphaVantageClient._request is internal but consistent with the
        # rest of the screener package
        overview = av._request({"function": "OVERVIEW", "symbol": ticker})

        float_shares: Optional[float] = None
        shares_outstanding = overview.get("SharesOutstanding")
        if shares_outstanding:
            float_shares = float(shares_outstanding) * 0.7

        market_cap: Optional[float] = None
        market_cap_raw = overview.get("MarketCapitalization")
        if market_cap_raw:
            market_cap = float(market_cap_raw)

        return float_shares, market_cap
    except Exception as exc:
        logger.warning("%s 市場データ取得失敗: %s", ticker, exc)
        return None, None


# ---------------------------------------------------------------------------
# Per-PR processing
# ---------------------------------------------------------------------------

def _process_entry(
    entry: dict,
    av: AlphaVantageClient,
    translate: bool,
) -> None:
    ticker = entry["ticker"]
    title = entry["title"]
    summary = entry["summary"]
    link = entry["link"]
    filed_at = entry["updated"]

    float_shares, market_cap = _fetch_market_info(ticker, av)

    if translate:
        try:
            result = translate_and_classify(title, summary)
            title_ja = result["title_ja"]
            summary_ja = result["summary_ja"]
            priority = result["priority"]
            key_figures = result["key_figures"]
        except Exception as exc:
            logger.warning("%s 翻訳失敗 → キーワード分類にフォールバック: %s", ticker, exc)
            title_ja = title
            summary_ja = summary
            priority = classify_priority(title, summary)
            key_figures = ""
    else:
        title_ja = title
        summary_ja = summary
        priority = classify_priority(title, summary)
        key_figures = ""

    logger.info("[%s] 新規PR [%s]: %s", ticker, priority, title_ja[:80])

    send_pr_notification(
        ticker=ticker,
        title_ja=title_ja,
        summary_ja=summary_ja,
        priority=priority,
        key_figures=key_figures,
        float_shares=float_shares,
        market_cap=market_cap,
        link=link,
        filed_at=filed_at,
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(
    tickers: list[str],
    interval: int,
    once: bool,
    translate: bool,
) -> None:
    av = AlphaVantageClient()
    logger.info(
        "PR通知Bot 起動 | tickers=%s | interval=%ds | translate=%s",
        tickers,
        interval,
        translate,
    )

    while True:
        logger.info("SEC EDGAR ポーリング中 ...")
        try:
            new_prs = poll_new_prs(tickers)
        except Exception as exc:
            logger.error("ポーリング失敗: %s", exc)
            new_prs = []

        if new_prs:
            logger.info("新規PR %d件を処理します", len(new_prs))
            for entry in new_prs:
                try:
                    _process_entry(entry, av, translate)
                    time.sleep(1)  # rate-limit between Discord posts
                except Exception as exc:
                    logger.error("[%s] PR通知失敗: %s", entry.get("ticker", "?"), exc)
        else:
            logger.info("新規PRなし")

        if once:
            break

        logger.info("%d秒待機 ...", interval)
        time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PR通知Bot — SEC EDGAR 8-K新着監視 → Discordへ日本語通知"
    )
    parser.add_argument(
        "--tickers",
        type=str,
        help="カンマ区切りのティッカー (例: AAPL,TSLA)。省略時は tickers.txt から読み込み",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="ポーリング間隔(秒)。デフォルト: 300",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="1回だけ実行して終了 (cronなどから呼ぶ場合に便利)",
    )
    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="OpenAI翻訳をスキップし英語のまま通知",
    )
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = read_tickers(Path("tickers.txt"))

    if not tickers:
        print(
            "エラー: ティッカーが指定されていません。"
            "--tickers か tickers.txt を設定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    run(
        tickers=tickers,
        interval=args.interval,
        once=args.once,
        translate=not args.no_translate,
    )


if __name__ == "__main__":
    main()
