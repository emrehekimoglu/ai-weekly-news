"""GitHub arama API'si: son 7 günde açılıp en çok yıldız alan Python AI projeleri."""

from datetime import datetime, timedelta, timezone

import requests

from newsletter.dates import parse_to_turkish_date
from newsletter.models import NewsItem


def fetch():
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    url = ("https://api.github.com/search/repositories?q=(topic:ai+OR+topic:llm+OR+topic:machine-learning)"
           f"+language:python+created:>{seven_days_ago}&sort=stars&order=desc")
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "newsletter-agent/1.0"}
    res = requests.get(url, headers=headers, timeout=10)
    if res.status_code != 200:
        return []
    items = []
    for repo in res.json().get("items", [])[:6]:
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
