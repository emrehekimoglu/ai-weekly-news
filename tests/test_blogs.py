"""Şirket blogları kaynağının ağ gerektirmeyen testleri (requests.get sahte yanıtlarla değiştirilir)."""

import json
import time
from email.utils import formatdate

import requests

from newsletter.sources import blogs

NOW = time.time()


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content
        self.text = content.decode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")


def rss(ages_in_days):
    items = "".join(
        f"<item><title>Yazı {i}</title><link>https://example.com/{i}</link>"
        f"<pubDate>{formatdate(NOW - age * 86400)}</pubDate><description>&lt;p&gt;Özet {i}&lt;/p&gt;</description></item>"
        for i, age in enumerate(ages_in_days))
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'.encode()


def anthropic_page(posts):
    """Next.js'in sayfaya gömdüğü biçimde (JSON metni JS dizgisi içinde) yazı listesi."""
    payload = json.dumps({"posts": [{"_type": "post", **p} for p in posts]}, ensure_ascii=False)
    chunk = json.dumps("1:" + payload, ensure_ascii=False)
    return f"<html><script>self.__next_f.push([1,{chunk}])</script></html>".encode()


def iso(age_in_days):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(NOW - age_in_days * 86400))


def post(slug, age_in_days, title="Başlık", summary="Özet"):
    return {"publishedOn": iso(age_in_days), "slug": {"_type": "slug", "current": slug},
            "summary": summary, "title": title}


def fake_get(routes, seen=None):
    def get(url, headers=None, **kwargs):
        if seen is not None:
            seen.append((url, (headers or {}).get("User-Agent", "")))
        body = routes.get(url)
        return FakeResponse(200, body) if body is not None else FakeResponse(404)
    return get


def test_every_company_is_fetched_with_descriptive_user_agent(monkeypatch):
    seen = []
    monkeypatch.setattr(requests, "get", fake_get({}, seen))
    blogs.fetch()

    assert [url for url, _ in seen if url != blogs.ANTHROPIC_MIRROR] == [url for _, url in blogs.FEEDS]
    assert {"Meta", "Microsoft", "NVIDIA", "Mistral AI", "Anthropic"} <= {name for name, _ in blogs.FEEDS}
    assert all(ua and not ua.startswith("python-requests") for _, ua in seen)


def test_feed_keeps_only_recent_posts_up_to_limit(monkeypatch):
    url = dict(blogs.FEEDS)["NVIDIA"]
    monkeypatch.setattr(requests, "get", fake_get({url: rss([20, 1, 2, 3, 4, 30])}))
    items = [i for i in blogs.fetch() if i.source == "NVIDIA"]

    assert [i.title for i in items] == ["Yazı 1", "Yazı 2", "Yazı 3"]
    assert items[0].summary == "Özet 1"


def test_anthropic_reads_official_news_page(monkeypatch):
    url = dict(blogs.FEEDS)["Anthropic"]
    page = anthropic_page([post("old", 30), post("new", 1, title="Yeni \"model\"", summary="Kısa özet"),
                           post("mid", 3), post("new", 1, title="Yeni \"model\"", summary="Kısa özet")])
    monkeypatch.setattr(requests, "get", fake_get({url: page}))
    items = [i for i in blogs.fetch() if i.source == "Anthropic"]

    assert [i.link for i in items] == ["https://www.anthropic.com/news/new", "https://www.anthropic.com/news/mid"]
    assert items[0].title == 'Yeni "model"'
    assert items[0].summary == "Kısa özet"


def test_anthropic_falls_back_to_mirror_when_page_has_no_posts(monkeypatch):
    url = dict(blogs.FEEDS)["Anthropic"]
    routes = {url: b"<html>yeni tasarim</html>", blogs.ANTHROPIC_MIRROR: rss([1])}
    monkeypatch.setattr(requests, "get", fake_get(routes))
    items = [i for i in blogs.fetch() if i.source == "Anthropic"]

    assert [i.link for i in items] == ["https://example.com/0"]


def test_anthropic_falls_back_to_mirror_when_page_fails(monkeypatch):
    monkeypatch.setattr(requests, "get", fake_get({blogs.ANTHROPIC_MIRROR: rss([1, 2])}))
    items = [i for i in blogs.fetch() if i.source == "Anthropic"]

    assert len(items) == 2
