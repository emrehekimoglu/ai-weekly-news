"""Ana akış: ayar kontrolü → veri toplama → LLM ile bülten → gönderim."""

import logging
import sys

from newsletter import config, llm, mailer, subscribers
from newsletter.sources import SOURCES, collect

log = logging.getLogger(__name__)


def setup_logging():
    # Sade biçim: "::error::" satırları GitHub Actions'ta hata olarak işaretlenir
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)


def main():
    setup_logging()
    if not config.DRY_RUN:
        problems = config.check_config()
        if problems:
            for p in problems:
                log.error("::error::%s", p)
            log.error("[HATA] Eksik ayarlar yüzünden çalışma durduruldu; veri toplanmadı, e-posta gönderilmedi.")
            sys.exit(1)

    by_source = collect(SOURCES)
    items = [item for source_items in by_source.values() for item in source_items]
    if not items:
        log.error("Hiçbir kaynaktan veri toplanamadı!")
        return

    if config.DRY_RUN:
        log.info("DRY_RUN: Toplam %d içerik toplandı. Model ve e-posta atlandı.", len(items))
        for name, source_items in by_source.items():
            log.info("%s: %d", name, len(source_items))
            for item in source_items:
                log.info("  - [%s] %s", item.source, item.title)
        return

    log.info("Toplam %d adet aday içerik toplandı. Modele aktarılıyor...", len(items))
    try:
        newsletter_html = llm.generate_digest(items)
    except Exception as e:
        # Bozuk bülten göndermek yerine çalışmayı hata ile bitir
        log.error("[HATA] %s. E-posta gönderilmedi.", e)
        sys.exit(1)

    sheets_error = None
    if config.PREVIEW:
        with open(config.PREVIEW_FILE, "w", encoding="utf-8") as f:
            f.write(newsletter_html)
        log.info("ÖNİZLEME: Bülten %s dosyasına kaydedildi; abonelere gönderilmeyecek.", config.PREVIEW_FILE)
        failed = mailer.send_all(newsletter_html, subscribers.get_preview_recipients(),
                                 subject=f"[ÖNİZLEME] {mailer.newsletter_subject()}")
    else:
        recipients, sheets_error = subscribers.get_subscribers()
        failed = mailer.send_all(newsletter_html, recipients)
    if failed is None or failed or sheets_error:
        sys.exit(1)
