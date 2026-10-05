"""GitHub arama API'si: son 7 günde açılıp en çok yıldız alan Python AI projeleri."""

import logging
import os
from datetime import datetime, timedelta, timezone

import requests

from newsletter.dates import parse_to_turkish_date
from newsletter.models import NewsItem

log = logging.getLogger(__name__)

API_URL = "https://api.github.com/search/repositories"
# Depo aramasında konu niteleyicileri arasında OR çalışmaz; her konu ayrı aranıp birleştirilir.
TOPICS = ["llm", "ai", "machine-learning"]
LIMIT = 6


def headers():
    h = {"Accept": "application/vnd.github+json", "User-Agent": "ai-weekly-news/1.0"}
    # Actions'ta GITHUB_TOKEN varsa kullanılır: kimliksiz arama paylaşılan runner IP'sinde hızla sınıra takılır.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def search(topic, since):
    params = {"q": f"topic:{topic} language:python created:>{since}", "sort": "stars", "order": "desc", "per_page": 20}
    res = requests.get(API_URL, params=params, headers=headers(), timeout=10)
    if res.status_code != 200:
        log.warning("GitHub '%s' araması HTTP %s döndü: %s", topic, res.status_code, res.text[:200])
        return []
    return res.json().get("items", [])


def fetch():
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    repos = {}
    for topic in TOPICS:
        for repo in search(topic, since):
            repos.setdefault(repo.get("id"), repo)
    top = sorted(repos.values(), key=lambda r: r.get("stargazers_count") or 0, reverse=True)[:LIMIT]
    items = []
    for repo in top:
        desc = repo.get("description") or "Açıklama belirtilmemiş."
        stars = repo.get("stargazers_count", 0)
        items.append(NewsItem(
            source="GitHub Açık Kaynak",
            title=f"{repo.get('full_name')} (⭐ {stars:,})",
            date=parse_to_turkish_date(repo.get("created_at", "")),
            link=repo.get("html_url"),
            summary=f"{desc} [Yıldız: {stars}]",
        ))
    return items
