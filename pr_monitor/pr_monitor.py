"""PR Monitor メインスクリプト."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    from pr_monitor.classifier import classify_pr
    from pr_monitor.discord_sender import DiscordSender
    from pr_monitor.market_data import MarketDataFetcher
    from pr_monitor.translator import Translator
except ModuleNotFoundError:
    from classifier import classify_pr
    from discord_sender import DiscordSender
    from market_data import MarketDataFetcher
    from translator import Translator

SEEN_FILE = Path(__file__).with_name("seen_ids.json")


def load_config(path: str = "pr_monitor/config.yaml") -> dict:
    raw = Path(path).read_text()
    try:
        import yaml  # type: ignore

        return yaml.safe_load(raw)
    except Exception:
        return _simple_yaml_load(raw)


def _simple_yaml_load(raw: str) -> dict:
    """Very small YAML subset parser for this project's config.yaml format."""
    result: dict = {}
    current: str | None = None
    nested: str | None = None

    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if line.startswith("  - ") and current and nested:
            result[current].setdefault(nested, []).append(line[4:].strip().strip('"'))
            continue

        if line.startswith("  ") and ":" in line and current:
            key, value = [part.strip() for part in line.strip().split(":", 1)]
            if value == "":
                nested = key
                result[current].setdefault(key, [])
            else:
                nested = None
                result[current][key] = _coerce_scalar(value)
            continue

        key, value = [part.strip() for part in line.split(":", 1)]
        if value == "":
            current = key
            nested = None
            result[current] = {}
        else:
            current = None
            nested = None
            result[key] = _coerce_scalar(value)

    return result


def _coerce_scalar(value: str):
    v = value.strip().strip('"')
    if v.lower() in {"true", "false"}:
        return v.lower() == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def load_seen_ids() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    data = json.loads(SEEN_FILE.read_text())
    return set(data.get("ids", []))


def save_seen_ids(seen: set[str]) -> None:
    trimmed = list(seen)[-5000:]
    SEEN_FILE.write_text(json.dumps({"ids": trimmed}, ensure_ascii=False, indent=2))


def fetch_pr_news(ticker: str, api_key: str, hours: int = 6) -> list[dict]:
    url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={ticker}&limit=20&apikey={api_key}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result: list[dict] = []
    for item in data:
        pub_str = item.get("publishedDate", "")
        try:
            pub_dt = datetime.strptime(pub_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if pub_dt >= cutoff:
                result.append(item)
        except Exception:
            result.append(item)
    return result


def process_ticker(
    ticker: str,
    config: dict,
    fetcher: MarketDataFetcher,
    translator: Translator,
    sender: DiscordSender,
    seen_ids: set[str],
    mode: str,
) -> int:
    sent = 0
    news_list = fetch_pr_news(ticker, config["fmp_api_key"], hours=int(config.get("lookback_hours", 6)))
    if not news_list:
        return 0

    quote = fetcher.get_quote(ticker)
    shares = fetcher.get_shares_info(ticker)

    market_cap = quote.get("market_cap") if quote else None
    is_penny = fetcher.is_penny_stock(market_cap, float(config["penny_threshold_usd"]))

    if mode == "penny" and not is_penny:
        return 0
    if mode == "large" and is_penny:
        return 0

    channel = "penny" if is_penny else "large_cap"

    for news in news_list:
        news_id = (news.get("url") or news.get("title") or "")[:160]
        if not news_id or news_id in seen_ids:
            continue
        seen_ids.add(news_id)

        title = news.get("title", "")
        body = news.get("text", "")
        pr_url = news.get("url", "")
        published_at = news.get("publishedDate", "")

        classification = classify_pr(title, body)
        if classification["tier"] == 3 and not is_penny:
            continue

        title_ja = translator.translate(title, max_chars=100)

        embed = sender.build_embed(
            ticker=ticker,
            pr_title=title,
            pr_title_ja=title_ja,
            pr_url=pr_url,
            published_at=published_at,
            classification=classification,
            quote=quote,
            shares=shares,
            market_fetcher=fetcher,
        )
        ok = sender.send(channel=channel, embed=embed, ping=classification.get("ping", False))
        if ok:
            sent += 1
        time.sleep(0.3)

    return sent


def resolve_mode(args: argparse.Namespace) -> str:
    if args.penny:
        return "penny"
    if args.large:
        return "large"
    return "all"


def main() -> None:
    parser = argparse.ArgumentParser(description="PR monitor for Discord channels")
    parser.add_argument("--penny", action="store_true", help="ペニー株チャンネルのみ")
    parser.add_argument("--large", action="store_true", help="大型株チャンネルのみ")
    parser.add_argument("--once", action="store_true", help="1回だけ実行")
    parser.add_argument("--ticker", type=str, help="特定銘柄のみ監視")
    parser.add_argument("--config", type=str, default="pr_monitor/config.yaml", help="config.yaml path")
    args = parser.parse_args()

    config = load_config(args.config)
    mode = resolve_mode(args)

    fetcher = MarketDataFetcher(config.get("fmp_api_key", ""))
    translator = Translator(
        engine=config.get("translation_engine", "none"),
        anthropic_api_key=config.get("anthropic_api_key", ""),
        deepl_api_key=config.get("deepl_api_key", ""),
    )
    sender = DiscordSender(
        penny_webhook=config.get("discord", {}).get("penny_webhook", ""),
        large_cap_webhook=config.get("discord", {}).get("large_cap_webhook", ""),
    )

    if args.ticker:
        tickers = [args.ticker.upper()]
    else:
        watch = config.get("watchlist", {})
        tickers = list(dict.fromkeys((watch.get("penny_stocks", []) + watch.get("large_caps", []))))

    seen_ids = load_seen_ids()

    while True:
        total_sent = 0
        for ticker in tickers:
            total_sent += process_ticker(ticker, config, fetcher, translator, sender, seen_ids, mode)

        save_seen_ids(seen_ids)
        if args.once:
            break
        time.sleep(int(config.get("poll_interval", 300)))


if __name__ == "__main__":
    main()
