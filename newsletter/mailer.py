"""E-posta biçimi (konu, düz metin, iptal bağlantısı) ve Gmail SMTP ile gönderim."""

import logging
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from urllib.parse import urlencode

from newsletter import config
from newsletter.dates import parse_to_turkish_date
from newsletter.render import render_html, render_text

log = logging.getLogger(__name__)

SENDER_NAME = "🤖 AI & Teknoloji Radarı"


def newsletter_subject(today=None):
    """Tarihli konu satırı; Gmail'in haftaları tek bir konuşmada toplamasını engeller."""
    today = today or datetime.now(timezone.utc)
    return f"🚀 Haftalık Yapay Zekâ & Teknoloji Radarı • {parse_to_turkish_date(today.strftime('%Y-%m-%d'))}"


def mask_email(email):
    """Loglar için adresi gizler: "emre@gmail.com" -> "e***@gmail.com"."""
    local, sep, domain = email.partition("@")
    return f"{local[:1]}***{sep}{domain}" if sep else "***"


def _describe_error(e):
    """Hata özeti; SMTP hataları alıcı adresini içerebildiği için metnini loga yazmaz."""
    code = getattr(e, "smtp_code", None)
    return f"{type(e).__name__} {code}" if code else type(e).__name__


def unsubscribe_url(email, token):
    """Aboneye özel iptal bağlantısı; web uygulaması veya token yoksa None."""
    if not (config.WEB_APP_URL and token):
        return None
    return f"{config.WEB_APP_URL}?{urlencode({'action': 'unsubscribe', 'email': email, 'token': token})}"


def build_message(digest, sub, subject):
    """Tek bir abone için şablondan HTML + düz metin e-postayı ve iptal başlığını hazırlar."""
    email = sub["email"]
    unsub_url = unsubscribe_url(email, sub.get("token", ""))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((SENDER_NAME, config.EMAIL_SENDER))
    msg["To"] = email
    if unsub_url:
        msg["List-Unsubscribe"] = f"<{unsub_url}>"

    # Düz metin önce, HTML sonra: istemciler desteklediği son parçayı gösterir
    msg.attach(MIMEText(render_text(digest, unsub_url), "plain", "utf-8"))
    msg.attach(MIMEText(render_html(digest, unsub_url), "html", "utf-8"))
    return msg


def send_all(digest, recipients, subject=None):
    """Bülteni her aboneye kendi kişisel iptal bağlantısıyla postalar.

    Gönderilemeyen adreslerin listesini, hiç alıcı yoksa None döndürür.
    """
    if not recipients:
        log.error("[HATA] Gönderilecek abone bulunamadı!")
        return None

    log.info("Toplam %d kişiye e-posta gönderimi başlıyor...", len(recipients))
    subject = subject or newsletter_subject()
    failed = []

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(config.EMAIL_SENDER, config.EMAIL_PASSWORD)
        for sub in recipients:
            email = sub["email"]
            try:
                server.sendmail(config.EMAIL_SENDER, email, build_message(digest, sub, subject).as_string())
                log.info("✓ Başarıyla gönderildi: %s", mask_email(email))
                time.sleep(1)
            except Exception as e:
                log.error("✗ Hata (%s): %s", mask_email(email), _describe_error(e))
                failed.append(email)

    sent = len(recipients) - len(failed)
    if failed:
        log.error("[HATA] %d/%d gönderim başarılı, %d başarısız: %s", sent, len(recipients), len(failed),
                  ", ".join(mask_email(f) for f in failed))
    else:
        log.info("Tüm gönderimler başarıyla tamamlandı! (%d/%d)", sent, len(recipients))
    return failed
