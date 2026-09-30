"""Ortak test yardımcıları: ayarları ve kaynakları ağ olmadan değiştirmek için."""

import pytest

from newsletter import app, config
from newsletter.models import NewsItem
from newsletter.sources import Source


def make_item(**kw):
    fields = {"source": "s", "title": "t", "date": "d", "link": "https://example.com/1", "summary": "x"}
    return NewsItem(**{**fields, **kw})


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
