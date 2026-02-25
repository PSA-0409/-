import pytest

from screener.notify import send_notion


class DummyResponse:
    def raise_for_status(self):
        return None


def test_send_notion_requires_env(monkeypatch):
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
    with pytest.raises(ValueError):
        send_notion("hello")


def test_send_notion_posts_page(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_DATABASE_ID", "db123")
    monkeypatch.setenv("NOTION_TITLE_PROPERTY", "Name")

    called = {}

    def fake_post(url, json, headers, timeout):
        called["url"] = url
        called["json"] = json
        called["headers"] = headers
        called["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("screener.notify.requests.post", fake_post)

    send_notion("line 1\n\nline2", title="Report")

    assert called["url"] == "https://api.notion.com/v1/pages"
    assert called["timeout"] == 15
    assert called["headers"]["Authorization"] == "Bearer secret"
    assert called["json"]["parent"]["database_id"] == "db123"
    assert called["json"]["properties"]["Name"]["title"][0]["text"]["content"] == "Report"
    assert len(called["json"]["children"]) >= 1
