"""Discord Embed生成・送信."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import requests

try:
    from pr_monitor.market_data import MarketDataFetcher
except ModuleNotFoundError:
    from market_data import MarketDataFetcher


class DiscordSender:
    def __init__(self, penny_webhook: str, large_cap_webhook: str):
        self.webhooks = {
            "penny": penny_webhook,
            "large_cap": large_cap_webhook,
        }

    def build_embed(
        self,
        ticker: str,
        pr_title: str,
        pr_title_ja: str,
        pr_url: str,
        published_at: str,
        classification: dict,
        quote: Optional[dict],
        shares: Optional[dict],
        market_fetcher: MarketDataFetcher,
    ) -> dict:
        price = quote.get("price") if quote else None
        price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "N/A"

        change_str = ""
        pct = quote.get("change_pct") if quote else None
        if isinstance(pct, (int, float)):
            change_str = f" {'▲' if pct >= 0 else '▼'}{abs(pct):.2f}%"

        mktcap_str = market_fetcher.format_money(quote.get("market_cap") if quote else None)
        float_str = market_fetcher.format_shares(shares.get("float_shares") if shares else None)

        free_float = shares.get("free_float_pct") if shares else None
        free_float_str = f"{free_float:.1f}%" if isinstance(free_float, (int, float)) else "N/A"

        vol_str = "N/A"
        if quote and isinstance(quote.get("volume"), (int, float)) and isinstance(quote.get("avg_volume"), (int, float)) and quote.get("avg_volume"):
            vol_ratio = quote["volume"] / quote["avg_volume"]
            vol_str = f"{quote['volume']:,.0f} ({vol_ratio:.1f}x avg)"

        title_prefix = "‼️ " if classification.get("tier") == 1 else ""
        embed_title = f"{title_prefix}{classification.get('emoji', '⚪')} [{ticker}] {pr_title_ja}"[:256]

        return {
            "title": embed_title,
            "url": pr_url,
            "color": classification.get("color", 0x808080),
            "description": f"**原題:** {pr_title[:200]}",
            "fields": [
                {"name": "📊 株価", "value": f"**{price_str}**{change_str}", "inline": True},
                {"name": "💰 時価総額", "value": mktcap_str, "inline": True},
                {"name": "📈 出来高", "value": vol_str, "inline": True},
                {"name": "🔄 浮動株", "value": float_str, "inline": True},
                {"name": "浮動株比率", "value": free_float_str, "inline": True},
                {"name": "🏷️ 重要度", "value": f"`{classification.get('label', '通常')}`", "inline": True},
            ],
            "footer": {
                "text": f"PR発表: {published_at} | Matched: {', '.join(classification.get('matched_keywords', [])[:3]) or 'general'}"
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def send(self, channel: str, embed: dict, ping: bool = False) -> bool:
        webhook_url = self.webhooks.get(channel)
        if not webhook_url:
            return False

        payload = {
            "content": "@here 🔴 **超重要PR検出**" if ping else "",
            "embeds": [embed],
            "username": "PR Monitor Bot",
            "avatar_url": "https://i.imgur.com/4M34hi2.png",
        }
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            return response.status_code == 204
        except Exception:
            return False
