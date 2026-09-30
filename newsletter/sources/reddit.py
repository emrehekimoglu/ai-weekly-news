"""Reddit: r/ChatGPT, r/singularity ve r/LocalLLaMA'nın haftalık öne çıkan paylaşımları.

Reddit, GitHub Actions gibi veri merkezi IP'lerinden gelen kimliksiz .json isteklerini
HTTP 403 ile engelliyor. REDDIT_CLIENT_ID/SECRET varsa OAuth API, yoksa birleşik RSS akışı kullanılır.
"""

import logging
import re
import time
from datetime import datetime

import feedparser
import requests

from newsletter import config
from newsletter.dates import parse_to_turkish_date
from newsletter.models import NewsItem

log = logging.getLogger(__name__)

SUBREDDITS = ["ChatGPT", "singularity", "LocalLLaMA"]
USER_AGENT = "python:ai-weekly-news:v1.1 (by /u/emrehekimoglu)"
MIN_SCORE = 300  # OAuth yolunda sadece toplulukta yüksek ilgi görmüş paylaşımlar


def _oauth_token():
    """REDDIT_CLIENT_ID/SECRET tanımlıysa uygulama (app-only) OAuth token'ı alır."""
    if not (config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET):
        return None
    try:
        res = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(config.REDDIT_CLIENT_ID, config.REDDIT_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": USER_AGENT},
            timeout=8,
        )
        res.raise_for_status()
        return res.json().get("access_token")
    except Exception as e:
        log.warning("Reddit OAuth token alınamadı: %s", e)
        return None


def _posts_json(sub, token):
    """OAuth ile top listesini çeker; JSON dönmezse None döner."""
    res = requests.get(
        f"https://oauth.reddit.com/r/{sub}/top?t=week&limit=6&raw_json=1",
        headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"},
        timeout=8,
    )
    content_type = res.headers.get("Content-Type", "")
    if res.status_code != 200 or "json" not in content_type:
        log.warning("Reddit r/%s JSON erişimi reddedildi (HTTP %s, %s)", sub, res.status_code, content_type or "?")
        return None
    return [p.get("data", {}) for p in res.json().get("data", {}).get("children", [])]


def _items_oauth(subreddits, token):
    items = []
    for sub in subreddits:
        try:
            for post in _posts_json(sub, token) or []:
                if post.get("score", 0) <= MIN_SCORE:
                    continue
                created = datetime.fromtimestamp(post.get("created_utc", 0))
                selftext = post.get("selftext", "")[:300].replace("\n", " ").strip()
                items.append(NewsItem(
                    source=f"Reddit r/{sub}",
                    title=post.get("title"),
                    date=parse_to_turkish_date(created.strftime("%Y-%m-%d")),
                    link=f"https://reddit.com{post.get('permalink')}",
                    summary=(f"[Viral Paylaşım - {post.get('score')} Upvote, {post.get('num_comments')} Yorum] "
                             f"{selftext}"),
                ))
        except Exception as e:
            log.warning("Reddit r/%s taranırken hata: %s", sub, e)
    return items


def _items_rss(subreddits, per_sub=5):
    """Tüm subreddit'lerin haftalık top RSS akışını TEK istekte çeker (upvote bilgisi yok, sıralama zaten skora göre).

    Kimliksiz istekler GitHub Actions IP'lerinde ilk bir-iki istekten sonra HTTP 429 alıyor,
    bu yüzden subreddit başına ayrı istek yerine birleşik (r/A+B+C) akış kullanılıyor.
    """
    url = f"https://www.reddit.com/r/{'+'.join(subreddits)}/top/.rss?t=week&limit=100"
    res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    if res.status_code == 429:
        retry_after = res.headers.get("Retry-After", "")
        wait = min(int(retry_after), 30) if retry_after.isdigit() else 10
        log.warning("Reddit RSS hız sınırı (HTTP 429), %s sn beklenip tekrar deneniyor...", wait)
        time.sleep(wait)
        res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    if res.status_code != 200:
        log.warning("Reddit RSS erişimi reddedildi (HTTP %s)", res.status_code)
        return []
    counts = {sub.lower(): 0 for sub in subreddits}
    items = []
    for entry in feedparser.parse(res.content).entries:
        match = re.search(r"/r/([^/]+)/", entry.get("link", ""))
        sub = match.group(1) if match else (entry.get("tags") or [{}])[0].get("term", "")
        if counts.get(sub.lower(), per_sub) >= per_sub:
            continue
        counts[sub.lower()] += 1
        content = entry.get("content", [{}])[0].get("value", "") or entry.get("summary", "")
        text = re.sub(r"<[^>]+>", " ", content).replace("submitted by", "")
        text = re.sub(r"\s+", " ", text).strip()[:300]
        items.append(NewsItem(
            source=f"Reddit r/{sub}",
            title=entry.title,
            date=parse_to_turkish_date(entry.get("updated_parsed", entry.get("published_parsed"))),
            link=entry.link,
            summary=f"[Haftanın En Çok Oylanan Paylaşımı] {text}",
        ))
    log.info("Reddit RSS: %s", ", ".join(f"r/{sub} {counts[sub.lower()]}" for sub in subreddits))
    return items


def fetch():
    token = _oauth_token()
    items = _items_oauth(SUBREDDITS, token) if token else _items_rss(SUBREDDITS)
    log.info("Reddit toplam %d içerik.", len(items))
    return items
