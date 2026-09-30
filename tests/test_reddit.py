"""Reddit RSS yedeğinin ağ gerektirmeyen testleri (requests.get sahte yanıtlarla değiştirilir)."""

import main


class FakeResponse:
    def __init__(self, status_code, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


def make_entry(sub, i):
    return (
        f'<entry><category term="{sub}"/><title>{sub} {i}</title>'
        f'<link href="https://www.reddit.com/r/{sub}/comments/{i}/x/"/>'
        f"<updated>2026-09-28T10:00:00+00:00</updated>"
        f'<content type="html">&lt;p&gt;Metin {i}&lt;/p&gt; submitted by u/a</content></entry>'
    )


def make_feed(entries):
    return ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">' + "".join(entries) + "</feed>").encode()


SUBS = ["ChatGPT", "singularity", "LocalLLaMA"]


def test_rss_caps_posts_per_subreddit_in_one_request(monkeypatch):
    calls = []
    feed = make_feed([make_entry("ChatGPT", i) for i in range(8)] + [make_entry("singularity", 1), make_entry("LocalLLaMA", 1)])

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(200, feed)

    monkeypatch.setattr(main.requests, "get", fake_get)
    items = main._reddit_items_rss(SUBS, per_sub=5)

    assert len(calls) == 1
    assert "r/ChatGPT+singularity+LocalLLaMA/top/.rss" in calls[0]
    sources = [item["source"] for item in items]
    assert sources.count("Reddit r/ChatGPT") == 5
    assert sources.count("Reddit r/singularity") == 1
    assert sources.count("Reddit r/LocalLLaMA") == 1
    assert items[0]["date"] == "28 Eylül 2026"
    assert "submitted by" not in items[0]["summary"]
    assert "<p>" not in items[0]["summary"]


def test_rss_retries_once_on_429(monkeypatch):
    responses = [FakeResponse(429, headers={"Retry-After": "1"}), FakeResponse(200, make_feed([make_entry("ChatGPT", 1)]))]
    sleeps = []
    monkeypatch.setattr(main.requests, "get", lambda url, **kwargs: responses.pop(0))
    monkeypatch.setattr(main.time, "sleep", sleeps.append)

    items = main._reddit_items_rss(SUBS)

    assert sleeps == [1]
    assert len(items) == 1


def test_rss_gives_up_after_second_429(monkeypatch):
    monkeypatch.setattr(main.requests, "get", lambda url, **kwargs: FakeResponse(429))
    monkeypatch.setattr(main.time, "sleep", lambda s: None)

    assert main._reddit_items_rss(SUBS) == []


def test_fetch_without_credentials_uses_rss_only(monkeypatch):
    monkeypatch.setattr(main, "REDDIT_CLIENT_ID", None)
    monkeypatch.setattr(main, "REDDIT_CLIENT_SECRET", None)
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(200, make_feed([make_entry("singularity", 1)]))

    monkeypatch.setattr(main.requests, "get", fake_get)
    items = main.fetch_reddit_viral_ai()

    assert len(calls) == 1 and ".rss" in calls[0]
    assert items[0]["source"] == "Reddit r/singularity"
