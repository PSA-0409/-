"""PR Notify: Discord embed notifications for press releases."""
from __future__ import annotations

from typing import Optional

import requests

from screener.utils import env_or_default

# ---------------------------------------------------------------------------
# Priority → Discord embed colour (decimal RGB)
# ---------------------------------------------------------------------------

_COLORS: dict[str, int] = {
    "critical": 0xFF0000,  # 赤  — 大型契約 / 政府 / M&A / FDA
    "high": 0xFF6B00,      # 橙  — 注目案件（百万ドル規模 / MOU等）
    "normal": 0x3B82F6,    # 青  — 通常PR
}

_LABELS: dict[str, str] = {
    "critical": "🔴 最重要（大型契約・政府・M&A・FDA）",
    "high":     "🟠 注目（契約・ライセンス・MOU）",
    "normal":   "🔵 通常PR",
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_shares(shares: Optional[float]) -> str:
    if shares is None:
        return "N/A"
    if shares >= 1_000_000:
        return f"{shares / 1_000_000:.2f}M株"
    if shares >= 1_000:
        return f"{shares / 1_000:.1f}K株"
    return f"{int(shares):,}株"


def _fmt_market_cap(cap: Optional[float]) -> str:
    if cap is None:
        return "N/A"
    if cap >= 1_000_000_000:
        return f"${cap / 1_000_000_000:.2f}B"
    if cap >= 1_000_000:
        return f"${cap / 1_000_000:.1f}M"
    return f"${cap:,.0f}"


# ---------------------------------------------------------------------------
# Discord embed sender
# ---------------------------------------------------------------------------

def send_pr_notification(
    *,
    ticker: str,
    title_ja: str,
    summary_ja: str,
    priority: str,
    key_figures: str,
    float_shares: Optional[float],
    market_cap: Optional[float],
    link: str,
    filed_at: str,
) -> None:
    """Send a colour-coded Discord embed for a single press release.

    Priority colours:
      critical → red  (大型契約 / 政府契約 / M&A / FDA承認)
      high     → orange
      normal   → blue
    """
    webhook_url = env_or_default("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        raise ValueError("DISCORD_WEBHOOK_URLが設定されていません")

    color = _COLORS.get(priority, _COLORS["normal"])
    label = _LABELS.get(priority, _LABELS["normal"])

    fields: list[dict] = [
        {"name": "優先度", "value": label, "inline": False},
        {
            "name": "浮動株 (Float)",
            "value": _fmt_shares(float_shares),
            "inline": True,
        },
        {
            "name": "時価総額 (Mkt Cap)",
            "value": _fmt_market_cap(market_cap),
            "inline": True,
        },
    ]
    if key_figures:
        fields.append({"name": "主要数値", "value": key_figures[:512], "inline": False})
    fields.append({"name": "提出日時 (UTC)", "value": filed_at, "inline": False})

    embed: dict = {
        "title": f"[{ticker}] {title_ja[:230]}",
        "description": summary_ja[:2000],
        "color": color,
        "fields": fields,
        "footer": {"text": "PR通知Bot | SEC EDGAR 8-K"},
    }
    if link:
        embed["url"] = link

    resp = requests.post(
        webhook_url, json={"embeds": [embed]}, timeout=10
    )
    resp.raise_for_status()
