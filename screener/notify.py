from __future__ import annotations

from datetime import datetime, timezone

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


def send_notion(message: str, title: str | None = None) -> None:
    notion_api_key = env_or_default("NOTION_API_KEY", "")
    database_id = env_or_default("NOTION_DATABASE_ID", "")
    title_property = env_or_default("NOTION_TITLE_PROPERTY", "Name")

    if not notion_api_key:
        raise ValueError("NOTION_API_KEYが設定されていません")
    if not database_id:
        raise ValueError("NOTION_DATABASE_IDが設定されていません")

    page_title = title or datetime.now(timezone.utc).strftime("Micro-float report %Y-%m-%d %H:%M UTC")
    chunks = chunk_markdown(message, limit=1800)
    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": chunk},
                    }
                ]
            },
        }
        for chunk in chunks
    ]

    payload = {
        "parent": {"database_id": database_id},
        "properties": {
            title_property: {
                "title": [
                    {
                        "type": "text",
                        "text": {"content": page_title},
                    }
                ]
            }
        },
        "children": children,
    }
    response = requests.post(
        "https://api.notion.com/v1/pages",
        json=payload,
        headers={
            "Authorization": f"Bearer {notion_api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    response.raise_for_status()
