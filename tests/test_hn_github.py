"""Hacker News ve GitHub kaynaklarının ağ gerektirmeyen testleri (requests.get sahte yanıtlarla değiştirilir)."""

import requests

from newsletter.sources import github, hackernews


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


def hn_hit(object_id, points, title="New AI model"):
    return {"objectID": object_id, "title": title, "points": points, "num_comments": 3,
            "created_at": "2026-09-28T10:00:00Z", "url": f"https://example.com/{object_id}"}


def test_hn_queries_each_keyword_and_merges_by_points(monkeypatch):
    calls = []
    results = {"AI": [hn_hit("1", 120), hn_hit("2", 80)], "LLM": [hn_hit("2", 80), hn_hit("3", 300)]}

    def fake_get(url, params=None, **kwargs):
        calls.append(params)
        assert "User-Agent" in kwargs["headers"]
        return FakeResponse(200, {"hits": results.get(params["query"], [])})

    monkeypatch.setattr(requests, "get", fake_get)
    items = hackernews.fetch()

    assert [c["query"] for c in calls] == hackernews.KEYWORDS
    assert all(" OR " not in c["query"] for c in calls)
    assert [i.link for i in items] == ["https://example.com/3", "https://example.com/1", "https://example.com/2"]
    assert items[0].summary == "Puan: 300, Yorum: 3"
    assert items[0].date == "28 Eylül 2026"


def test_hn_skips_failed_keyword_and_untitled_hits(monkeypatch):
    def fake_get(url, params=None, **kwargs):
        if params["query"] == "AI":
            return FakeResponse(429)
        return FakeResponse(200, {"hits": [hn_hit("9", 60), {"objectID": "10", "points": 999}]})

    monkeypatch.setattr(requests, "get", fake_get)
    items = hackernews.fetch()
    assert [i.link for i in items] == ["https://example.com/9"]


def test_hn_drops_prefix_only_matches(monkeypatch):
    hits = [hn_hit("1", 90, "Airport delays"), hn_hit("2", 80, "ChatGPT gets memory"), hn_hit("3", 70, "Local LLMs on a Mac")]
    monkeypatch.setattr(requests, "get", lambda url, params=None, **kw: FakeResponse(200, {"hits": hits}))
    assert [i.link for i in hackernews.fetch()] == ["https://example.com/2", "https://example.com/3"]


def gh_repo(repo_id, stars):
    return {"id": repo_id, "full_name": f"o/r{repo_id}", "stargazers_count": stars, "description": None,
            "created_at": "2026-09-27T00:00:00Z", "html_url": f"https://github.com/o/r{repo_id}"}


def test_github_searches_each_topic_and_ranks_by_stars(monkeypatch):
    calls = []
    results = {"llm": [gh_repo(1, 50), gh_repo(2, 900)], "ai": [gh_repo(2, 900), gh_repo(3, 200)]}

    def fake_get(url, params=None, headers=None, **kwargs):
        calls.append(params["q"])
        topic = params["q"].split()[0].removeprefix("topic:")
        return FakeResponse(200, {"items": results.get(topic, [])})

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(requests, "get", fake_get)
    items = github.fetch()

    assert len(calls) == len(github.TOPICS)
    assert all(" OR " not in q and "(" not in q for q in calls)
    assert [i.link for i in items] == ["https://github.com/o/r2", "https://github.com/o/r3", "https://github.com/o/r1"]
    assert items[0].title == "o/r2 (⭐ 900)"
    assert items[0].summary == "Açıklama belirtilmemiş. [Yıldız: 900]"


def test_github_uses_token_when_available(monkeypatch):
    seen = []

    def fake_get(url, params=None, headers=None, **kwargs):
        seen.append(headers.get("Authorization"))
        return FakeResponse(403)

    monkeypatch.setenv("GITHUB_TOKEN", "abc")
    monkeypatch.setattr(requests, "get", fake_get)
    assert github.fetch() == []
    assert seen and all(h == "Bearer abc" for h in seen)
