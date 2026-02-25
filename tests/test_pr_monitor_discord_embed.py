from pr_monitor.discord_sender import DiscordSender
from pr_monitor.market_data import MarketDataFetcher


def test_build_embed_fields():
    sender = DiscordSender("https://example.com/a", "https://example.com/b")
    fetcher = MarketDataFetcher("demo")
    embed = sender.build_embed(
        ticker="ASTS",
        pr_title="Awarded contract",
        pr_title_ja="契約受注",
        pr_url="https://example.com/news",
        published_at="2026-02-25 14:30:00",
        classification={"tier": 1, "emoji": "🔴", "label": "超重要", "color": 0xFF0000, "matched_keywords": ["contract"]},
        quote={"price": 8.42, "change_pct": 12.5, "market_cap": 1_500_000_000, "volume": 45200000, "avg_volume": 5400000},
        shares={"float_shares": 180_500_000, "free_float_pct": 65.3},
        market_fetcher=fetcher,
    )
    assert embed["title"].startswith("‼️ 🔴 [ASTS]")
    assert embed["color"] == 0xFF0000
    assert len(embed["fields"]) == 6
