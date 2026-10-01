"""Türk teknoloji basını: "Türkiye'den" bölümü için yerli girişim ve yapay zeka haberleri.

Genel akışlarda sadece yapay zeka, girişim ve yatırım haberleri tutulur; bir haftadan eski girdiler atlanır.
Bölüm isteğe bağlıdır: akışlar boş dönerse veya model uygun haber bulamazsa bülten bölümsüz gider.
"""

import calendar
import logging
import re
import time

from newsletter.models import NewsItem
from newsletter.sources.feeds import entry_date, fetch_feed

log = logging.getLogger(__name__)

# (ad, adres, sadece anahtar kelimeli haberler mi)
FEEDS = [
    ("Webrazzi", "https://webrazzi.com/kategori/yapay-zeka/feed/", False),
    ("Webrazzi", "https://webrazzi.com/kategori/girisim/feed/", False),
    ("Egirişim", "https://egirisim.com/feed/", True),
    ("Webtekno", "https://www.webtekno.com/rss.xml", True),
]
PER_FEED = 5
MAX_AGE_DAYS = 8
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
KEYWORDS = re.compile(
    r"yapay zek|\bai\b|\bllm|gpt|openai|gemini|claude|makine öğren|girişim|yatırım|startup|robot|veri merkez|çip",
    re.IGNORECASE)


def _text(html, limit):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()[:limit]


def _is_recent(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return not parsed or time.time() - calendar.timegm(parsed) <= MAX_AGE_DAYS * 24 * 3600


def fetch():
    items = []
    for name, url, filtered in FEEDS:
        try:
            count = 0
            for entry in fetch_feed(url, headers=HEADERS).entries:
                if count >= PER_FEED:
                    break
                title = " ".join(entry.get("title", "").split())
                summary = _text(entry.get("summary", ""), 350)
                if not title or not _is_recent(entry) or (filtered and not KEYWORDS.search(f"{title} {summary}")):
                    continue
                count += 1
                items.append(NewsItem(source=name, title=title, date=entry_date(entry), link=entry.link,
                                      summary=summary or title, turkish=True))
            log.info("%s (%s): %d haber", name, url, count)
        except Exception as e:
            log.warning("%s beslemesinde atlama: %s", name, e)
    return items
