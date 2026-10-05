"""'Türkiye'den' bölümü: Türk kaynakları, model seçimi, şablon ve geçmiş (ağ yok)."""

import json
import time

import pytest
import requests

from newsletter import config, history
from newsletter.llm import build_prompt, parse_digest
from newsletter.render import render_html, render_text
from newsletter.sources import turkey
from tests.conftest import make_digest, make_item
from tests.test_reddit import FakeResponse

ITEMS = [make_item(title=f"Ham {i}", link=f"https://example.com/{i}", turkish=i > 6) for i in range(1, 11)]


class FeedResponse(FakeResponse):
    def raise_for_status(self):
        pass


def answer(turkiye):
    picks = [{"id": i, "title": f"Haber {i}", "category": "Araştırma", "summary": f"Özet {i}."} for i in range(1, 6)]
    return json.dumps({"intro": "Giriş.", "items": picks, "turkiye": turkiye}, ensure_ascii=False)


def rss(entries):
    body = "".join(f"<item><title>{t}</title><link>https://tr.example.com/{i}</link><description>{d}</description>"
                   f"<pubDate>{p}</pubDate></item>" for i, (t, d, p) in enumerate(entries))
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()


def test_feeds_keep_recent_ai_and_startup_news(monkeypatch):
    now = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
    feed = rss([
        ("Yerli girişim 5 milyon dolar yatırım aldı", "<p>Detay</p>", now),
        ("Yeni telefon tanıtıldı", "Kamera", now),
        ("Yapay zeka modeli", "Eski haber", "Mon, 01 Jan 2024 10:00:00 +0000"),
    ])
    monkeypatch.setattr(turkey, "FEEDS", [("Kategori", "https://a", False), ("Genel", "https://b", True)])
    monkeypatch.setattr(requests, "get", lambda url, **kw: FeedResponse(200, feed))
    items = turkey.fetch()
    assert [(i.source, i.title) for i in items] == [
        ("Kategori", "Yerli girişim 5 milyon dolar yatırım aldı"), ("Kategori", "Yeni telefon tanıtıldı"),
        ("Genel", "Yerli girişim 5 milyon dolar yatırım aldı"),
    ]
    assert all(i.turkish for i in items) and items[0].summary == "Detay"


def test_broken_feed_is_skipped(monkeypatch):
    def fail(url, **kw):
        raise requests.Timeout("yavaş")
    monkeypatch.setattr(requests, "get", fail)
    assert turkey.fetch() == []


def test_prompt_marks_turkish_sources():
    prompt = build_prompt(ITEMS)
    assert "[7] Kaynak: s (Türkiye)\n" in prompt and "[1] Kaynak: s\n" in prompt
    assert '"turkiye": [{"id": 7,' in prompt


def test_parse_reads_turkiye_picks():
    digest = parse_digest(answer([{"id": "8", "title": " Yerli  girişim ", "summary": "Yatırım aldı."}]), ITEMS)
    assert [(e.item.link, e.title, e.category) for e in digest.turkiye] == [
        ("https://example.com/8", "Yerli girişim", "Türkiye")]


@pytest.mark.parametrize("turkiye", [
    None, [], "metin", [{"id": 2, "title": "Yabancı", "summary": "Türk kaynağı değil."}],
    [{"id": 99, "title": "x", "summary": "y"}], [{"id": 7, "title": "", "summary": "y"}], ["bozuk"],
])
def test_bad_or_empty_turkiye_skips_section_without_failing(turkiye):
    digest = parse_digest(answer(turkiye), ITEMS)
    assert len(digest.entries) == 5 and digest.turkiye == []


def test_turkiye_drops_repeats_and_caps():
    picks = [{"id": i, "title": f"T{i}", "summary": "Özet."} for i in (7, 7, 8, 9, 10)]
    digest = parse_digest(answer(picks), ITEMS)
    assert [e.title for e in digest.turkiye] == ["T7", "T8", "T9"]


def test_template_shows_section_only_when_present():
    assert "TÜRKİYE'DEN" not in render_html(make_digest()) and "TÜRKİYE'DEN" not in render_text(make_digest())
    digest = make_digest()
    digest.turkiye = [digest.entries.pop()]
    html, text = render_html(digest), render_text(digest)
    assert "TÜRKİYE'DEN" in html
    assert 'href="https://example.com/5"' in html
    assert "TÜRKİYE'DEN\n\n• Haber 5\n" in text


def test_history_records_turkiye_links(set_config):
    digest = make_digest()
    digest.turkiye = [digest.entries.pop()]
    history.record(digest, "2026-10-05")
    assert "example.com/5" in history.seen_links(history.load(config.HISTORY_FILE))
