"""Kırık bağlantı kontrolü: sadece kesin ölü bağlantılar elenir, botları engelleyen siteler kalır (ağ yok)."""

import json

import pytest
import requests

from newsletter import app, config, linkcheck, llm
from tests.conftest import make_item


@pytest.fixture
def responses(monkeypatch, set_config):
    """responses({url: durum kodu veya fırlatılacak hata}) ile _fetch'i taklit eder; yapılan çağrıları döndürür."""
    set_config(LINK_CHECK=True)
    calls = []

    def apply(table, head=None):
        def fake_fetch(method, url):
            calls.append((method, url))
            result = (head or {}).get(url, table[url]) if method == "HEAD" else table[url]
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setattr(linkcheck, "_fetch", fake_fetch)
        return calls
    return apply


DNS_ERROR = requests.ConnectionError("Failed to resolve 'olu.example' ([Errno -2] Name or service not known)")


@pytest.mark.parametrize("result,reason", [
    (200, None),
    (403, None),  # botlara kapalı (TechSpot gibi), okur için açılıyor
    (429, None),
    (503, None),  # Cloudflare sayfası veya geçici sunucu hatası
    (404, "HTTP 404"),
    (410, "HTTP 410"),
    (DNS_ERROR, "alan adı bulunamadı"),
    (requests.ConnectionError("Connection refused"), "bağlantı kurulamadı"),
    (requests.Timeout("yavaş"), None),
    (requests.exceptions.SSLError("sertifika"), "bağlantı kurulamadı"),
])
def test_check_link(responses, result, reason):
    responses({"https://a.example/x": result})
    assert linkcheck.check_link("https://a.example/x") == reason


def test_head_404_is_confirmed_with_get(responses):
    """HEAD'e 404 dönüp GET'te açılan sunucular var; onlar ölü sayılmaz."""
    calls = responses({"https://a.example/x": 200}, head={"https://a.example/x": 404})
    assert linkcheck.check_link("https://a.example/x") is None
    assert calls == [("HEAD", "https://a.example/x"), ("GET", "https://a.example/x")]


def test_alive_link_needs_only_head(responses):
    calls = responses({"https://a.example/x": 200})
    linkcheck.check_link("https://a.example/x")
    assert calls == [("HEAD", "https://a.example/x")]


def test_non_http_link_is_not_checked(responses):
    calls = responses({})
    assert linkcheck.check_link("") is None
    assert linkcheck.check_link("ftp://a.example/x") is None
    assert calls == []


def _items(statuses):
    return [make_item(title=f"Haber {i}", link=f"https://a.example/{i}") for i in range(len(statuses))]


def test_dead_items_are_dropped_and_reported(responses, isolated_report):
    statuses = [200, 404, 403, 200, 200]
    items = _items(statuses)
    responses({item.link: status for item, status in zip(items, statuses)})
    kept = linkcheck.remove_dead(items)
    assert [item.title for item in kept] == ["Haber 0", "Haber 2", "Haber 3", "Haber 4"]
    warnings = json.loads(isolated_report.read_text(encoding="utf-8"))["warnings"]
    assert len(warnings) == 1
    assert "1 aday haberin bağlantısı kırık" in warnings[0]
    assert "Haber 1 (HTTP 404): https://a.example/1" in warnings[0]


def test_no_warning_when_all_links_alive(responses, isolated_report):
    items = _items([200, 200])
    responses({item.link: 200 for item in items})
    assert linkcheck.remove_dead(items) == items
    assert not isolated_report.exists() or not json.loads(isolated_report.read_text())["warnings"]


def test_mass_failure_drops_nothing(responses, isolated_report):
    """Çoğu bağlantı açılmıyorsa sorun ağdadır; bülten boşalmasın diye hiçbir haber elenmez."""
    items = _items([404, 404, 200])
    responses({item.link: DNS_ERROR for item in items})
    assert linkcheck.remove_dead(items) == items
    warnings = json.loads(isolated_report.read_text(encoding="utf-8"))["warnings"]
    assert "kontrolü bu hafta atlandı" in warnings[0]


def test_same_link_checked_once(responses):
    items = [make_item(title="A", link="https://a.example/1"), make_item(title="B", link="https://a.example/1")]
    calls = responses({"https://a.example/1": 200})
    linkcheck.remove_dead(items)
    assert calls == [("HEAD", "https://a.example/1")]


def test_disabled_check_makes_no_requests(responses, set_config):
    calls = responses({})
    set_config(LINK_CHECK=False)
    items = _items([200])
    assert linkcheck.remove_dead(items) == items
    assert calls == []


def test_model_never_sees_dead_links(monkeypatch, responses, set_config, fake_sources):
    items = _items([200, 410, 200, 200])
    fake_sources(items)
    responses({item.link: status for item, status in zip(items, [200, 410, 200, 200])})
    set_config(DRY_RUN=False, PREVIEW=True)
    monkeypatch.setattr(config, "check_config", lambda: [])
    seen = []

    def fake_generate(candidates, previous=()):
        seen.extend(candidates)
        raise RuntimeError("model burada durur")
    monkeypatch.setattr(llm, "generate_digest", fake_generate)
    with pytest.raises(SystemExit):
        app.main()
    assert [item.title for item in seen] == ["Haber 0", "Haber 2", "Haber 3"]
