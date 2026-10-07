"""Şirket blogları: yapay zeka şirketlerinin resmi duyuruları.

Her şirketten son MAX_AGE_DAYS gün içindeki en fazla PER_FEED yazı alınır; sessiz geçen şirket bülende yer kaplamaz.
Anthropic'in RSS beslemesi yok: haber sayfasındaki gömülü yazı listesi okunur, olmazsa RSSHub aynasına düşülür.
"""

import calendar
import json
import logging
import re
import time
from datetime import datetime

import feedparser
import requests

from newsletter.dates import parse_to_turkish_date
from newsletter.models import NewsItem
from newsletter.sources.feeds import entry_date

log = logging.getLogger(__name__)

FEEDS = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "https://deepmind.google/blog/feed/basic/"),
    ("Anthropic", "https://www.anthropic.com/news"),
    ("Meta", "https://about.fb.com/news/tag/ai/feed/"),
    ("Microsoft", "https://blogs.microsoft.com/feed/"),
    ("NVIDIA", "https://blogs.nvidia.com/blog/category/generative-ai/feed/"),
    ("Mistral AI", "https://mistral.ai/rss.xml"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
]
ANTHROPIC_MIRROR = "https://rsshub.bestblogs.dev/anthropic/news"
PER_FEED = 3
MAX_AGE_DAYS = 8
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _text(html, limit):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()[:limit]


def _is_recent(timestamp):
    return timestamp is None or time.time() - timestamp <= MAX_AGE_DAYS * 24 * 3600


def _get(url):
    res = requests.get(url, headers=HEADERS, timeout=8)
    res.raise_for_status()
    return res


def _feed_items(name, url):
    items = []
    for entry in feedparser.parse(_get(url).content).entries:
        if len(items) >= PER_FEED:
            break
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        title = " ".join(entry.get("title", "").split())
        if not title or not _is_recent(calendar.timegm(parsed) if parsed else None):
            continue
        items.append(NewsItem(source=name, title=title, date=entry_date(entry), link=entry.link,
                              summary=_text(entry.get("summary", ""), 350) or title))
    return items


def _anthropic_posts(html):
    """Haber sayfasının Next.js verisindeki yazıları (yayın tarihi, slug, başlık, özet olanlar) yeniden eskiye döndürür."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    data = "".join(json.loads(f'"{chunk}"') for chunk in chunks)
    decoder = json.JSONDecoder()
    posts = {}
    for match in re.finditer(r'\{\s*"_type"\s*:\s*"post"', data):
        try:
            post, _ = decoder.raw_decode(data, match.start())
        except ValueError:
            continue
        slug = (post.get("slug") or {}).get("current")
        if slug and post.get("publishedOn") and post.get("title"):
            posts[slug] = post
    return sorted(posts.values(), key=lambda p: p["publishedOn"], reverse=True)


def _anthropic_items(posts, url):
    items = []
    for post in posts[:PER_FEED]:
        published = datetime.fromisoformat(post["publishedOn"].replace("Z", "+00:00"))
        if not _is_recent(published.timestamp()):
            break
        title = " ".join(post["title"].split())
        items.append(NewsItem(source="Anthropic", title=title, date=parse_to_turkish_date(post["publishedOn"]),
                              link=f"{url}/{post['slug']['current']}",
                              summary=_text(post.get("summary", ""), 350) or title))
    return items


def _anthropic(url):
    """Önce resmi haber sayfası; sayfa okunamazsa veya içinden yazı çıkmazsa RSSHub aynası."""
    try:
        posts = _anthropic_posts(_get(url).text)
        if posts:
            return _anthropic_items(posts, url), url
        log.warning("Anthropic haber sayfasında yazı bulunamadı, aynaya geçiliyor")
    except Exception as e:
        log.warning("Anthropic haber sayfası okunamadı, aynaya geçiliyor: %s", e)
    return _feed_items("Anthropic", ANTHROPIC_MIRROR), ANTHROPIC_MIRROR


def fetch():
    items = []
    for name, url in FEEDS:
        try:
            found, used = _anthropic(url) if name == "Anthropic" else (_feed_items(name, url), url)
            log.info("%s (%s): %d yazı", name, used, len(found))
            items.extend(found)
        except Exception as e:
            log.warning("%s beslemesinde atlama: %s", name, e)
    return items
