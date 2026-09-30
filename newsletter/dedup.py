"""Aynı haberin birden fazla kaynaktan veya art arda iki sayıda gelmesini engelleyen yardımcılar."""

import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

log = logging.getLogger(__name__)

TRACKING_PARAMS = re.compile(r"^(utm_.*|ref|ref_src|source|fbclid|gclid|mc_cid|mc_eid)$", re.IGNORECASE)


def normalize_link(url):
    """Karşılaştırma için bağlantıyı sadeleştirir: şema, www./old.reddit, izleme parametreleri, # ve sondaki / atılır."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    if host == "old.reddit.com":
        host = "reddit.com"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k)))
    return urlunsplit(("", host, parts.path.rstrip("/"), query, "")).lstrip("/")


def normalize_title(title):
    """Karşılaştırma için başlığı küçük harfe çevirip noktalama ve fazla boşlukları atar."""
    return " ".join(re.sub(r"[^\w\s]", " ", (title or "").casefold()).split())


def remove_duplicates(items):
    """Aynı bağlantıya veya aynı başlığa sahip haberlerden ilkini (kaynak sırasına göre) tutar."""
    seen_links, seen_titles, unique = set(), set(), []
    for item in items:
        link, title = normalize_link(item.link), normalize_title(item.title)
        if (link and link in seen_links) or (title and title in seen_titles):
            log.info("Tekrar eden haber atlandı: [%s] %s", item.source, item.title)
            continue
        seen_links.add(link)
        seen_titles.add(title)
        unique.append(item)
    return unique
