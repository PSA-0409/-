"""PR Monitor: SEC EDGAR 8-K filings polling via Atom RSS feed."""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

SEEN_FILE = Path("outputs/pr_seen.json")
EDGAR_BASE = "https://www.sec.gov"
_HEADERS = {"User-Agent": "PRNotificationBot/1.0 contact@screener.example"}
_NS = {"a": "http://www.w3.org/2005/Atom"}


def _load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False))


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_recent_8k(ticker: str) -> list[dict]:
    """Fetch recent 8-K filing entries for *ticker* from SEC EDGAR Atom feed."""
    url = (
        f"{EDGAR_BASE}/cgi-bin/browse-edgar"
        f"?action=getcompany&CIK={ticker}&type=8-K"
        f"&dateb=&owner=include&count=10&search_text=&output=atom"
    )
    resp = requests.get(url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    entries = []
    for entry in root.findall("a:entry", _NS):
        uid = (entry.findtext("a:id", "", _NS) or "").strip()
        title = (entry.findtext("a:title", "", _NS) or "").strip()
        updated = (entry.findtext("a:updated", "", _NS) or "").strip()
        link_el = entry.find("a:link", _NS)
        link = link_el.get("href", "") if link_el is not None else ""
        summary_el = entry.find("a:summary", _NS)
        summary_raw = (summary_el.text or "") if summary_el is not None else ""
        summary = _strip_html(summary_raw)

        entries.append(
            {
                "ticker": ticker.upper(),
                "uid": uid,
                "title": title,
                "updated": updated,
                "link": link,
                "summary": summary,
            }
        )
    return entries


def poll_new_prs(tickers: list[str], sleep_between: float = 1.0) -> list[dict]:
    """Poll SEC EDGAR for new 8-K filings across *tickers*.

    Returns only entries not previously seen. Updates the seen-set on disk.
    """
    seen = _load_seen()
    new_entries: list[dict] = []

    for ticker in tickers:
        try:
            entries = fetch_recent_8k(ticker)
            for entry in entries:
                if entry["uid"] not in seen:
                    new_entries.append(entry)
                    seen.add(entry["uid"])
        except Exception:
            pass  # Caller should log errors
        if sleep_between > 0:
            time.sleep(sleep_between)

    _save_seen(seen)
    return new_entries
