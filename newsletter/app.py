"""Ana akış: ayar kontrolü → veri toplama → tekrarları ve kırık bağlantıları eleme → LLM ile seçki → şablondan e-posta → gönderim."""

import json
import logging
import sys
from datetime import datetime, timezone

from newsletter import config, history, linkcheck, llm, mailer, report, stats, subscribers, welcome
from newsletter.dedup import remove_duplicates
from newsletter.render import render_html
from newsletter.sources import SOURCES, collect

log = logging.getLogger(__name__)


def setup_logging():
    # Sade biçim: "::error::" satırları GitHub Actions'ta hata olarak işaretlenir
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)


def write_post_summary(digest, date):
    """Telegram gönderisi için sayının kısa özeti (newsletter/telegram.py okur)."""
    summary = {
        "date": date,
        "headline": digest.headline,
        "intro": digest.intro,
        "tldr": digest.tldr,
        "titles": [e.title for e in digest.entries],
    }
    with open(config.POST_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def main():
    setup_logging()
    if (config.SCHEDULED and not (config.DRY_RUN or config.PREVIEW)
            and history.scheduled_send_within(history.load(), days=6)):
        log.info("Bu hafta otomatik çalışma sayıyı zaten gönderdi; yedek çalışma bir şey yapmadan bitti.")
        return
    if not config.DRY_RUN:
        problems = config.check_config()
        if problems:
            for p in problems:
                log.error("::error::%s", p)
            log.error("[HATA] Eksik ayarlar yüzünden çalışma durduruldu; veri toplanmadı, e-posta gönderilmedi.")
            sys.exit(1)

    report.reset()
    by_source = collect(SOURCES)
    report.set_sources({name: len(source_items) for name, source_items in by_source.items()})
    collected = [item for source_items in by_source.values() for item in source_items]
    if not collected:
        log.error("[HATA] Hiçbir kaynaktan veri toplanamadı! E-posta gönderilmedi.")
        if config.DRY_RUN:
            return
        sys.exit(1)

    past_issues = history.load()
    items = linkcheck.remove_dead(history.remove_seen(remove_duplicates(collected), past_issues))

    if config.DRY_RUN:
        log.info("DRY_RUN: Toplam %d içerik toplandı, tekrarlar, önceki sayılardakiler ve kırık bağlantılılar "
                 "çıkınca %d kaldı. Model ve e-posta atlandı.", len(collected), len(items))
        for name, source_items in by_source.items():
            log.info("%s: %d", name, len(source_items))
            for item in source_items:
                log.info("  - [%s] %s", item.source, item.title)
        return

    if not items:
        log.error("[HATA] Tekrarlar çıkınca yeni haber kalmadı. E-posta gönderilmedi.")
        sys.exit(1)

    log.info("Toplam %d adet aday içerik toplandı. Modele aktarılıyor...", len(items))
    try:
        digest = llm.generate_digest(items, history.recent_titles(past_issues))
    except Exception as e:
        # Bozuk bülten göndermek yerine çalışmayı hata ile bitir
        log.error("[HATA] %s. E-posta gönderilmedi.", e)
        sys.exit(1)

    sheets_error = None
    if config.PREVIEW:
        with open(config.PREVIEW_FILE, "w", encoding="utf-8") as f:
            f.write(render_html(digest))
        log.info("ÖNİZLEME: Bülten %s dosyasına kaydedildi; abonelere gönderilmeyecek.", config.PREVIEW_FILE)
        failed = mailer.send_all(digest, subscribers.get_preview_recipients(),
                                 subject=f"{'[YEDEK MODEL TESTİ] ' if config.FALLBACK_TEST else ''}"
                                         f"[ÖNİZLEME] {mailer.newsletter_subject(digest=digest)}")
    else:
        recipients, sheets_error = subscribers.get_subscribers()
        failed = mailer.send_all(digest, recipients)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if failed is not None and len(failed) < len(recipients):
            history.record(digest, today, scheduled=config.SCHEDULED)
            # Web arşivi için ortak (kişisel iptal bağlantısı olmayan) sürüm
            with open(config.ARCHIVE_FILE, "w", encoding="utf-8") as f:
                f.write(render_html(digest))
            # Yeni okurlar onayda bu sayıyı hemen alsın diye (Worker gönderir)
            welcome.save(digest, mailer.issue_id(), mailer.newsletter_subject(digest=digest))
            write_post_summary(digest, today)
        # Sadece abone listesi Sheets'ten okunduysa; önizleme ve DRY_RUN buraya hiç gelmez
        if failed is not None and sheets_error is None:
            stats.record(today, sent=len(recipients) - len(failed), failed=len(failed))
    if failed is None or failed or sheets_error:
        sys.exit(1)
