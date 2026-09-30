"""Hacker News (Algolia): son 7 günün en çok oy alan AI gelişmeleri."""

import time

import requests

from newsletter.dates import parse_to_turkish_date
from newsletter.models import NewsItem


def fetch():
    seven_days_ago = int(time.time()) - (7 * 24 * 3600)
    url = ("https://hn.algolia.com/api/v1/search_by_date?query=AI%20OR%20LLM%20OR%20Grok%20OR%20Claude%20OR%20OpenAI"
           f"&tags=story&numericFilters=points>50,created_at_i>{seven_days_ago}")
    hits = requests.get(url, timeout=10).json().get("hits", [])[:6]
    return [
        NewsItem(
            source="Hacker News",
            title=hit.get("title"),
            date=parse_to_turkish_date(hit.get("created_at", "")),
            link=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            summary=f"Puan: {hit.get('points')}, Yorum: {hit.get('num_comments')}",
        )
        for hit in hits
    ]
