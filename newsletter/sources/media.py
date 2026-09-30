"""Bağımsız teknoloji basını: The Verge ve Ars Technica."""

import logging

from newsletter.models import NewsItem
from newsletter.sources.feeds import clean, entry_date, fetch_feed

log = logging.getLogger(__name__)

FEEDS = [
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
]


def fetch():
    items = []
    for name, url in FEEDS:
        try:
            for entry in fetch_feed(url).entries[:4]:
                items.append(NewsItem(
                    source=name,
                    title=entry.title,
                    date=entry_date(entry),
                    link=entry.link,
                    summary=clean(entry.get("summary", ""), 350),
                ))
        except Exception as e:
            log.warning("%s beslemesinde atlama: %s", name, e)
    return items
