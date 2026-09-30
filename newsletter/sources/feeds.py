"""RSS/Atom akışlarını zaman aşımıyla çekme."""

import feedparser
import requests

from newsletter import config
from newsletter.dates import parse_to_turkish_date


def fetch_feed(url, headers=None):
    """RSS/Atom akışını zaman aşımıyla çeker ve feedparser ile ayrıştırır."""
    res = requests.get(url, headers=headers, timeout=config.FEED_TIMEOUT_SECONDS)
    res.raise_for_status()
    return feedparser.parse(res.content)


def entry_date(entry):
    """Akış girdisinin yayın (yoksa güncelleme) tarihini Türkçe döndürür."""
    return parse_to_turkish_date(entry.get("published_parsed", entry.get("updated_parsed")))


def clean(text, limit):
    """Satır sonlarını kaldırıp metni kısaltır."""
    return text[:limit].replace("\n", " ").strip()
