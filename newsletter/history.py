"""Önceki sayılarda yer alan haberlerin kaydı (depodaki JSON dosyası, iş akışı tarafından commit edilir).

Böylece aynı haber iki hafta üst üste seçilmez: daha önce gönderilen bağlantılar modele hiç gitmez,
son sayıların başlıkları da modele "bunları tekrar seçme" diye verilir.
"""

import json
import logging
import os

from newsletter import config
from newsletter.dedup import normalize_link

log = logging.getLogger(__name__)


def load(path=None):
    """Kayıtlı sayıları (en eskiden en yeniye) döndürür; dosya yoksa veya bozuksa boş liste."""
    path = path or config.HISTORY_FILE
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            issues = json.load(f).get("issues", [])
        return issues if isinstance(issues, list) else []
    except (OSError, ValueError, AttributeError) as e:
        log.warning("Geçmiş dosyası okunamadı (%s), yok sayılıyor: %s", path, e)
        return []


def seen_links(issues):
    return {normalize_link(entry.get("link")) for issue in issues for entry in issue.get("entries", [])} - {""}


def recent_titles(issues, weeks=2):
    """Son `weeks` sayıda seçilen haber başlıkları (modele tekrar seçmemesi için verilir)."""
    return [entry["title"] for issue in issues[-weeks:] for entry in issue.get("entries", []) if entry.get("title")]


def remove_seen(items, issues):
    """Önceki sayılarda gönderilmiş bağlantıya sahip haberleri çıkarır."""
    seen = seen_links(issues)
    fresh = [item for item in items if normalize_link(item.link) not in seen]
    if len(fresh) < len(items):
        log.info("Önceki sayılarda yer alan %d haber çıkarıldı.", len(items) - len(fresh))
    return fresh


def record(digest, date, path=None):
    """Gönderilen sayıyı kaydeder; sadece son HISTORY_ISSUES sayı tutulur."""
    path = path or config.HISTORY_FILE
    issues = [issue for issue in load(path) if issue.get("date") != date]
    issues.append({
        "date": date,
        "entries": [{"title": e.title, "link": e.item.link, "source": e.item.source} for e in digest.entries],
    })
    issues = issues[-config.HISTORY_ISSUES:]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"issues": issues}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log.info("Sayı geçmişe kaydedildi: %s (%d haber)", path, len(digest.entries))
