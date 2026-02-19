from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from screener.indicators import build_indicator_snapshot
from screener.notify import send_discord
from screener.report import build_report
from screener.schemas import LlmTickerPayload
from screener.finnhub_client import FinnhubClient
from screener.spread import compute_spread_proxy
from screener.utils import (
    OUTPUT_DIR,
    iter_with_pause,
    now_timestamp,
    read_tickers,
    save_json,
    save_text,
    setup_logger,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Micro-float stock screener")
    parser.add_argument("--tickers", type=str, default="", help="Comma-separated tickers")
    parser.add_argument("--notify", type=str, default="", help="Notification channel (discord)")
    parser.add_argument("--interval", type=str, default="1m", help="Preferred interval (1m/5m)")
    parser.add_argument("--top", type=int, default=5, help="Top candidates count")
    parser.add_argument("--sleep", type=float, default=0.4, help="Sleep seconds between tickers")
    return parser.parse_args()


def build_payload(
    snapshot,
    indicators,
    intraday_available: bool,
    interval: str,
    data_notes: str,
) -> LlmTickerPayload:
    float_note = None
    if snapshot.float_info.estimated:
        float_note = snapshot.float_info.rationale or "推定"
    spread_proxy = indicators.spread_proxy

    return LlmTickerPayload(
        ticker=snapshot.ticker,
        float_shares=snapshot.float_info.shares,
        float_note=float_note,
        today_vol=snapshot.today_volume,
        avg_vol=snapshot.avg_volume,
        rvol=indicators.rvol,
        rotation=indicators.rotation,
        vwap=indicators.vwap,
        vdu_ratio=indicators.vdu_ratio,
        range_ratio=indicators.range_ratio,
        last_price=snapshot.price,
        day_high=snapshot.high,
        day_low=snapshot.low,
        open=snapshot.open_price,
        previous_close=snapshot.previous_close,
        catalyst_summary="",
        dilution_flags="",
        spread_l2_notes=spread_proxy,
        session_high=indicators.levels.session_high,
        session_low=indicators.levels.session_low,
        range_upper=indicators.levels.range_upper,
        range_lower=indicators.levels.range_lower,
        ignition_level_candidate=indicators.levels.ignition_level_candidate,
        first_pullback_low_candidate=indicators.levels.first_pullback_low_candidate,
        intraday_interval=interval,
        intraday_available=intraday_available,
        data_notes=data_notes,
    )


def load_tickers(arg_tickers: str) -> list[str]:
    if arg_tickers:
        return [t.strip().upper() for t in arg_tickers.split(",") if t.strip()]
    file_tickers = read_tickers(Path("tickers.txt"))
    return file_tickers


def main() -> int:
    load_dotenv()
    args = parse_args()
    logger = setup_logger()

    tickers = load_tickers(args.tickers)
    if not tickers:
        logger.error("ティッカーが指定されていません")
        return 1

    client = FinnhubClient()
    payloads: list[LlmTickerPayload] = []

    for ticker in iter_with_pause(tickers, args.sleep):
        try:
            snapshot, intraday = client.fetch_snapshot(ticker, preferred_interval=args.interval)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s の取得に失敗しました: %s", ticker, exc)
            continue

        data_notes = ""
        if not snapshot.intraday_available:
            data_notes = "日中データ不足のため一部指標は推定/欠損"

        indicator = build_indicator_snapshot(
            today_volume=snapshot.today_volume,
            avg_volume=snapshot.avg_volume,
            float_shares=snapshot.float_info.shares,
            intraday=intraday,
            interval=snapshot.intraday_interval,
            spread_proxy=compute_spread_proxy(snapshot, intraday),
        )

        payloads.append(
            build_payload(
                snapshot=snapshot,
                indicators=indicator,
                intraday_available=snapshot.intraday_available,
                interval=snapshot.intraday_interval,
                data_notes=data_notes,
            )
        )

    if not payloads:
        logger.error("有効なティッカーがありません")
        return 1

    logger.info("ルールベースレポートを生成します")
    report = build_report(payloads, top_n=args.top)

    timestamp = now_timestamp()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_text(report, OUTPUT_DIR / f"{timestamp}_analysis.md")
    save_json(payloads, OUTPUT_DIR / f"{timestamp}_payload.json")
    logger.info("レポート保存完了: outputs/%s_analysis.md", timestamp)

    if args.notify.lower() == "discord":
        send_discord(report)
        logger.info("Discordへ通知しました")
    else:
        logger.info("通知はスキップされました")

    return 0


if __name__ == "__main__":
    sys.exit(main())
