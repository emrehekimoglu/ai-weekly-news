"""Ortak test yardımcıları: ayarları ve kaynakları ağ olmadan değiştirmek için."""

import pytest

from newsletter import app, config, report, stats
from newsletter.models import Digest, DigestEntry, NewsItem, Stat
from newsletter.sources import Source


def make_item(**kw):
    fields = {"source": "s", "title": "t", "date": "d", "link": "https://example.com/1", "summary": "x"}
    return NewsItem(**{**fields, **kw})


def make_digest(count=5, cover=False):
    entries = [DigestEntry(item=make_item(link=f"https://example.com/{i}", date="28 Eylül 2026"),
                           title=f"Haber {i}", category="Yeni Model", summary=f"Özet {i}.")
               for i in range(1, count + 1)]
    digest = Digest(intro="Haftanın özeti.", entries=entries, date="29 Eylül 2026")
    if cover:
        digest.headline = "Açık kaynak arayı kapattı mı?"
        digest.tldr = ["Birinci madde.", "İkinci madde.", "Üçüncü madde."]
        digest.stat = Stat(value="10 GW", label="Rekor çip siparişi.")
    return digest


@pytest.fixture(autouse=True)
def isolated_history(monkeypatch, tmp_path):
    """Testler depodaki data/history.json dosyasına asla dokunmaz."""
    path = tmp_path / "history.json"
    monkeypatch.setattr(config, "HISTORY_FILE", str(path))
    return path


@pytest.fixture(autouse=True)
def isolated_welcome(monkeypatch, tmp_path):
    """Testler depodaki data/latest-issue.json dosyasına asla dokunmaz."""
    path = tmp_path / "latest-issue.json"
    monkeypatch.setattr(config, "WELCOME_FILE", str(path))
    return path


@pytest.fixture(autouse=True)
def isolated_report(monkeypatch, tmp_path):
    """Çalışma raporu depo köküne değil geçici klasöre yazılır."""
    path = tmp_path / "run_report.json"
    monkeypatch.setattr(config, "REPORT_FILE", str(path))
    report.reset()
    return path


@pytest.fixture(autouse=True)
def isolated_post_file(monkeypatch, tmp_path):
    """Telegram özeti (issue.json) depo köküne değil geçici klasöre yazılır."""
    path = tmp_path / "issue.json"
    monkeypatch.setattr(config, "POST_FILE", str(path))
    return path


@pytest.fixture(autouse=True)
def no_sheets_network(monkeypatch):
    """Testler gerçek Google Sheets'e asla bağlanmaz."""
    def fail():
        raise RuntimeError("testte Sheets'e bağlanılmaz")
    monkeypatch.setattr(stats, "_open_spreadsheet", fail)


@pytest.fixture(autouse=True)
def no_share_links(monkeypatch):
    """CI'daki GITHUB_REPOSITORY arşiv adresini doldurmasın; paylaşım testleri bunları açıkça verir."""
    monkeypatch.setattr(config, "SIGNUP_URL", "")
    monkeypatch.setattr(config, "ARCHIVE_URL", "")


@pytest.fixture(autouse=True)
def no_link_checks(monkeypatch):
    """Testler haber bağlantılarını gerçekten açmaya çalışmaz; test_linkcheck.py açıkça açar."""
    monkeypatch.setattr(config, "LINK_CHECK", False)


@pytest.fixture
def set_config(monkeypatch):
    """set_config(AD=değer, ...) ile newsletter.config değerlerini test süresince değiştirir."""
    def apply(**values):
        for name, value in values.items():
            monkeypatch.setattr(config, name, value)
    return apply


@pytest.fixture
def fake_sources(monkeypatch):
    """Gerçek kaynaklar yerine verilen öğeleri döndüren tek bir kaynak kullanır."""
    def apply(items=None, fetch=None):
        monkeypatch.setattr(app, "SOURCES", [Source("Sahte", "sahte kaynak", fetch or (lambda: list(items or [])))])
    return apply
