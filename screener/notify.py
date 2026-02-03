from __future__ import annotations

import requests

from screener.utils import chunk_markdown, env_or_default


def send_discord(message: str) -> None:
    webhook_url = env_or_default("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        raise ValueError("DISCORD_WEBHOOK_URLが設定されていません")

    chunks = chunk_markdown(message)
    for chunk in chunks:
        response = requests.post(webhook_url, json={"content": chunk}, timeout=10)
        response.raise_for_status()
