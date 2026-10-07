"""Kırık bağlantı kontrolü: bağlantısı açıkça ölü olan aday haberler modele gitmeden elenir.

Model seçimden önce yapılır; böylece model kırık bir haberi hiç seçemez, sayı eksik kalmaz ve
ek model çağrısı gerekmez. Sadece kesin ölü bağlantılar elenir: 404/410, alan adı bulunamadı
(DNS) veya iki denemede de bağlantı kurulamaması. Botları engelleyen yanıtlar (403, 429,
Cloudflare sayfaları), 5xx ve zaman aşımı "canlı" sayılır; okur için açılıyor olabilirler
(ör. TechSpot botlara 403 dönüyor ama tarayıcıda açılıyor).
"""

import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from newsletter import config, report

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/128.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}
TIMEOUT_SECONDS = 10
MAX_WORKERS = 16
DEAD_STATUSES = {404, 410}
# Adayların bu orandan fazlası ölü görünüyorsa sorun bağlantılarda değil çalışma ortamındadır; hiçbiri elenmez
MAX_DEAD_RATIO = 0.5


def _fetch(method, url):
    """HTTP durum kodunu döndürür; bağlantı kurulamazsa requests hatası fırlatır."""
    with requests.request(method, url, headers=HEADERS, timeout=TIMEOUT_SECONDS,
                          allow_redirects=True, stream=True) as res:
        return res.status_code


def check_link(url):
    """Bağlantı kesin ölüyse nedenini (ör. "HTTP 404"), değilse None döndürür."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        status = _fetch("HEAD", url)
        if status not in DEAD_STATUSES:
            return None
    except requests.Timeout:
        return None
    except requests.RequestException:
        pass
    # HEAD'i yanlış işleyen sunucular var; ölü demeden önce GET ile bir kez daha bakılır
    try:
        status = _fetch("GET", url)
    except requests.Timeout:
        return None
    except requests.ConnectionError as e:
        return "alan adı bulunamadı" if "resolve" in str(e).lower() else "bağlantı kurulamadı"
    except requests.RequestException:
        return None
    return f"HTTP {status}" if status in DEAD_STATUSES else None


def remove_dead(items):
    """Bağlantısı ölü haberleri çıkarır, elenenleri çalışma raporuna (uyarı e-postasına) yazar."""
    if not config.LINK_CHECK or not items:
        return items
    links = list(dict.fromkeys(item.link for item in items))
    log.info("%d bağlantı kırık bağlantı için kontrol ediliyor...", len(links))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        dead = {link: reason for link, reason in zip(links, pool.map(check_link, links)) if reason}
    if not dead:
        log.info("✓ Kırık bağlantı yok.")
        return items
    if len(dead) > len(links) * MAX_DEAD_RATIO:
        report.warn(f"Bağlantıların {len(dead)}/{len(links)} tanesi açılamadı; çalışma ortamının ağında "
                    "sorun olabilir, kırık bağlantı kontrolü bu hafta atlandı")
        return items

    kept, dropped = [], []
    for item in items:
        if item.link in dead:
            dropped.append(f"[{item.source}] {item.title} ({dead[item.link]}): {item.link}")
        else:
            kept.append(item)
    for line in dropped:
        log.info("Kırık bağlantılı haber atlandı: %s", line)
    report.warn(f"{len(dropped)} aday haberin bağlantısı kırık olduğu için modele gönderilmedi:\n  "
                + "\n  ".join(dropped))
    return kept
