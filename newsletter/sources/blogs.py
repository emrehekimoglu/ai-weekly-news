"""Şirket blogları: OpenAI, Google DeepMind, Anthropic ve Hugging Face resmi duyuruları."""

import logging

import feedparser
import requests

from newsletter.models import NewsItem
from newsletter.sources.feeds import clean, entry_date

log = logging.getLogger(__name__)

FEEDS = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "https://deepmind.google/blog/feed/basic/"),
    ("Anthropic", "https://rsshub.bestblogs.dev/anthropic/news"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch():
    items = []
    for name, url in FEEDS:
        try:
            res = requests.get(url, headers=HEADERS, timeout=8)
            if res.status_code != 200:
                continue
            for entry in feedparser.parse(res.content).entries[:3]:
                title = entry.title.replace("\n", " ").strip()
                items.append(NewsItem(
                    source=name,
                    title=title,
                    date=entry_date(entry),
                    link=entry.link,
                    summary=clean(entry.get("summary", ""), 350) or title,
                ))
        except Exception as e:
            log.warning("%s RSS beslemesinde atlama: %s", name, e)
    return items
