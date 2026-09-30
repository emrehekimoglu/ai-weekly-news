"""Haber kaynakları: her kaynak NewsItem listesi döndüren bir fonksiyondur.

Yeni kaynak eklemek için modülünü yazıp SOURCES listesine eklemek yeterli.
"""

import logging
from dataclasses import dataclass
from typing import Callable

from newsletter.models import NewsItem
from newsletter.sources import arxiv, blogs, github, hackernews, media, reddit

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Source:
    name: str
    description: str
    fetch: Callable[[], list[NewsItem]]


SOURCES = [
    Source("arXiv", "arXiv makaleleri", arxiv.fetch),
    Source("Hacker News", "Hacker News AI trendleri", hackernews.fetch),
    Source("GitHub", "GitHub açık kaynak AI projeleri", github.fetch),
    Source("Şirket blogları", "Şirket blogları (OpenAI, DeepMind, Anthropic, Hugging Face)", blogs.fetch),
    Source("Reddit", "Reddit viral AI olayları ve tartışmaları", reddit.fetch),
    Source("Teknoloji basını", "Bağımsız teknoloji basını (The Verge, Ars Technica)", media.fetch),
]


def collect(sources):
    """Kaynakları sırayla tarar; hata veren kaynak loglanıp atlanır. {kaynak adı: [NewsItem]} döndürür."""
    results = {}
    for i, source in enumerate(sources, 1):
        log.info("%d/%d - %s taranıyor...", i, len(sources), source.description)
        try:
            results[source.name] = source.fetch()
        except Exception as e:
            log.warning("%s çekilirken hata: %s", source.name, e)
            results[source.name] = []
    return results
