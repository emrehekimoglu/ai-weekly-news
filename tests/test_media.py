"""Teknoloji basını kaynağının ağ gerektirmeyen testleri (requests.get sahte yanıtlarla değiştirilir)."""

import requests

from newsletter.sources import media


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")


FEED = (
    b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
    + b"".join(
        f'<entry><title>Haber {i}</title><link href="https://example.com/{i}"/>'
        f"<updated>2026-09-28T10:00:00+00:00</updated><summary>Ozet {i}</summary></entry>".encode()
        for i in range(6)
    )
    + b"</feed>"
)


def test_sends_descriptive_user_agent(monkeypatch):
    seen = []

    def fake_get(url, headers=None, **kwargs):
        seen.append((headers or {}).get("User-Agent", ""))
        return FakeResponse(200, FEED)

    monkeypatch.setattr(requests, "get", fake_get)
    items = media.fetch()

    assert len(seen) == len(media.FEEDS)
    assert all(ua and not ua.startswith("python-requests") for ua in seen)
    assert [i.source for i in items] == ["The Verge AI"] * 4 + ["Ars Technica"] * 4


def test_blocked_feed_does_not_stop_others(monkeypatch):
    def fake_get(url, **kwargs):
        return FakeResponse(403) if "theverge" in url else FakeResponse(200, FEED)

    monkeypatch.setattr(requests, "get", fake_get)
    items = media.fetch()

    assert {i.source for i in items} == {"Ars Technica"}
