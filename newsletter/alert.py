"""Uyarı e-postası: bülten çalışması hata ile biterse veya bir kaynak boş dönerse sahibine çalışma kaydının bağlantısını yollar.

GitHub zamanlanmış çalışmaların hatalarını her zaman bildirmez; bu yüzden iş akışının son adımı
`python -m newsletter.alert --status <job.status> --log run.log` olarak her gerçek gönderimde çalışır.
Önizleme ve dry_run'da çağrılmaz. Ağır kütüphaneleri (jinja2, openai) içe aktarmaz; kurulum adımı
başarısız olsa bile çalışabilsin.
"""

import argparse
import logging
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from newsletter import config, report
from newsletter.dates import parse_to_turkish_date

log = logging.getLogger(__name__)

LOG_TAIL_LINES = 40
MAIN_CRON = "0 3 * * 1"


def run_url():
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo, run_id = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    return f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else None


def recipient():
    """ALERT_EMAIL, yoksa PREVIEW_EMAIL, yoksa gönderen adres (sahibin kendi Gmail'i)."""
    for email in (config.ALERT_EMAIL, os.environ.get("PREVIEW_EMAIL", ""), config.EMAIL_SENDER or ""):
        if "@" in (email or ""):
            return email.strip()
    return None


def log_tail(path, lines=LOG_TAIL_LINES):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            tail = f.read().splitlines()[-lines:]
    except OSError:
        return []
    # GitHub Actions işaretleri e-postada gürültü
    return [line.replace("::error::", "").replace("::warning::", "") for line in tail]


def build_alert(status, rep, tail, url=None, schedule="", today=None):
    """(konu, metin) döndürür; bildirilecek bir şey yoksa None."""
    failed = status != "success"
    warnings = rep.get("warnings") or []
    if not failed and not warnings:
        return None

    date = parse_to_turkish_date((today or datetime.now(timezone.utc)).strftime("%Y-%m-%d"))
    if failed:
        subject = f"⚠️ Bülten çalışması başarısız • {date}"
        lines = ["Haftalık bülten çalışması hata ile bitti. Abonelere e-posta hiç gitmemiş "
                 "veya bazılarına gitmemiş olabilir; ayrıntı aşağıdaki kayıtta."]
        if schedule == MAIN_CRON:
            lines.append("Bu 03:00 UTC'deki otomatik çalışmaydı. Sayı gönderilmediyse 04:37 UTC'deki "
                         "yedek çalışma kendiliğinden tekrar dener.")
    else:
        subject = f"⚠️ Bülten gönderildi, {len(warnings)} uyarı var • {date}"
        lines = ["Bülten abonelere gönderildi, ama dikkat edilmesi gereken bir şey var."]

    lines.append("")
    lines.append(f"Çalışma kaydı: {url}" if url else "Çalışma kaydı: GitHub → Actions sekmesi")
    if warnings:
        lines += ["", "Uyarılar:"] + [f"- {w}" for w in warnings]
    sources = rep.get("sources") or {}
    if sources:
        lines += ["", "Kaynaklardan gelen haber sayısı:"] + [f"- {name}: {count}" for name, count in sources.items()]
    if failed and tail:
        lines += ["", f"Kaydın son {len(tail)} satırı:", ""] + tail
    return subject, "\n".join(lines) + "\n"


def send(subject, body, to):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("AI Radarı uyarı", config.EMAIL_SENDER))
    msg["To"] = to
    msg["Date"] = formatdate(usegmt=True)
    msg["Message-ID"] = make_msgid(domain=config.EMAIL_SENDER.rpartition("@")[2] or None)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(config.EMAIL_SENDER, config.EMAIL_PASSWORD)
        server.sendmail(config.EMAIL_SENDER, to, msg.as_string())


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", default="failure", help="GitHub job.status: success, failure veya cancelled")
    parser.add_argument("--log", default="run.log", help="bülten çalışmasının çıktısı")
    args = parser.parse_args(argv)

    alert = build_alert(args.status, report.load(), log_tail(args.log), run_url(),
                        os.environ.get("EVENT_SCHEDULE", ""))
    if alert is None:
        log.info("Sorun yok; uyarı e-postası gerekmedi.")
        return 0
    to = recipient()
    if not (config.EMAIL_SENDER and config.EMAIL_PASSWORD and to):
        log.error("::error::Uyarı e-postası gönderilemedi: EMAIL_SENDER / EMAIL_PASSWORD eksik.")
        return 1
    try:
        send(*alert, to)
    except Exception as e:
        log.error("::error::Uyarı e-postası gönderilemedi: %s", type(e).__name__)
        return 1
    log.info("Uyarı e-postası gönderildi: %s", alert[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
