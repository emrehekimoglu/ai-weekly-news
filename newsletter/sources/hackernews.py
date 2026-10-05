"""Hacker News (Algolia): son 7 günün en çok oy alan AI gelişmeleri."""

import logging
import re
import time

import requests

from newsletter.dates import parse_to_turkish_date
from newsletter.models import NewsItem

log = logging.getLogger(__name__)

API_URL = "https://hn.algolia.com/api/v1/search"
HEADERS = {"User-Agent": "ai-weekly-news/1.0 (+https://github.com/emrehekimoglu/ai-weekly-news)"}
# Algolia "OR" operatörünü desteklemez: tüm kelimeleri AND ile arar ve "OR" da bir kelime sayılır.
# Bu yüzden her anahtar kelime ayrı sorgulanıp sonuçlar birleştirilir.
KEYWORDS = ["AI", "LLM", "OpenAI", "Anthropic", "Claude", "Gemini", "GPT", "Grok"]
# Algolia son kelimeyi önek olarak eşleştirir ("AI" -> "Airport"); başlıkta tam kelime aranır.
TITLE_PATTERN = re.compile(r"\b(ai|llms?|openai|anthropic|claude|gemini|grok)\b|gpt", re.IGNORECASE)
MIN_POINTS = 50
LIMIT = 6


def search(keyword, since):
    params = {
        "query": keyword,
        "tags": "story",
        "numericFilters": f"points>{MIN_POINTS},created_at_i>{since}",
        "hitsPerPage": 50,
    }
    res = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
    if res.status_code != 200:
        log.warning("Hacker News '%s' araması HTTP %s döndü", keyword, res.status_code)
        return []
    return res.json().get("hits", [])


def fetch():
    since = int(time.time()) - (7 * 24 * 3600)
    hits = {}
    for keyword in KEYWORDS:
        for hit in search(keyword, since):
            if TITLE_PATTERN.search(hit.get("title") or ""):
                hits.setdefault(hit.get("objectID"), hit)
    top = sorted(hits.values(), key=lambda h: h.get("points") or 0, reverse=True)[:LIMIT]
    return [
        NewsItem(
            source="Hacker News",
            title=hit.get("title"),
            date=parse_to_turkish_date(hit.get("created_at", "")),
            link=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            summary=f"Puan: {hit.get('points')}, Yorum: {hit.get('num_comments')}",
        )
        for hit in top
    ]
