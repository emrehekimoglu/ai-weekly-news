"""Bağımsız teknoloji basını: The Verge ve Ars Technica.

The Verge'ün CDN'i requests'in varsayılan "python-requests/x" User-Agent'ını HTTP 403
(X-Forbidden) ile reddediyor; tanımlayıcı bir User-Agent ile GitHub Actions'tan da erişilebiliyor.
"""

import html
import logging

from newsletter.models import NewsItem
from newsletter.sources.feeds import clean, entry_date, fetch_feed

log = logging.getLogger(__name__)

FEEDS = [
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
]
HEADERS = {"User-Agent": "ai-weekly-news/1.0 (+https://github.com/emrehekimoglu/ai-weekly-news)"}


def fetch():
    items = []
    for name, url in FEEDS:
        try:
            for entry in fetch_feed(url, headers=HEADERS).entries[:4]:
                items.append(NewsItem(
                    source=name,
                    title=html.unescape(entry.title),  # The Verge başlıkları &#8217; gibi varlıklarla geliyor
                    date=entry_date(entry),
                    link=entry.link,
                    summary=clean(entry.get("summary", ""), 350),
                ))
        except Exception as e:
            log.warning("%s beslemesinde atlama: %s", name, e)
    return items
