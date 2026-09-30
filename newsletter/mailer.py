"""E-posta biçimi (konu, düz metin, iptal bağlantısı) ve Gmail SMTP ile gönderim."""

import logging
import re
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from html.parser import HTMLParser
from urllib.parse import urlencode

from newsletter import config
from newsletter.dates import parse_to_turkish_date

log = logging.getLogger(__name__)

SENDER_NAME = "🤖 AI & Teknoloji Radarı"


def newsletter_subject(today=None):
    """Tarihli konu satırı; Gmail'in haftaları tek bir konuşmada toplamasını engeller."""
    today = today or datetime.now(timezone.utc)
    return f"🚀 Haftalık Yapay Zekâ & Teknoloji Radarı • {parse_to_turkish_date(today.strftime('%Y-%m-%d'))}"


def unsubscribe_url(email, token):
    """Aboneye özel iptal bağlantısı; web uygulaması veya token yoksa None."""
    if not (config.WEB_APP_URL and token):
        return None
    return f"{config.WEB_APP_URL}?{urlencode({'action': 'unsubscribe', 'email': email, 'token': token})}"


class _TextExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "div", "br", "hr", "h1", "h2", "h3", "h4", "li", "tr", "table", "body"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.href = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self.skip += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "a":
            self.href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "a" and self.href:
            if self.href.startswith("http"):
                self.parts.append(f" ({self.href})")
            self.href = None

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html):
    """HTML bülteninden düz metin sürümü üretir (bağlantılar parantez içinde)."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def build_message(html_content, sub, subject):
    """Tek bir abone için HTML + düz metin e-postayı ve iptal başlığını hazırlar."""
    email = sub["email"]
    unsub_url = unsubscribe_url(email, sub.get("token", ""))

    footer_html = f"""
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0 15px 0;">
    <p style="text-align: center; font-size: 12px; color: #94a3b8; font-family: sans-serif;">
      Bu bülteni AI & Teknoloji Radarı'na abone olduğunuz için alıyorsunuz.<br>
      Abonelikten ayrılmak isterseniz <a href="{unsub_url or '#'}" style="color: #64748b; text-decoration: underline;">buraya tıklayabilirsiniz</a>.
    </p>
    """
    personalized_html = html_content.replace("</body>", f"{footer_html}</body>")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((SENDER_NAME, config.EMAIL_SENDER))
    msg["To"] = email
    if unsub_url:
        msg["List-Unsubscribe"] = f"<{unsub_url}>"

    # Düz metin önce, HTML sonra: istemciler desteklediği son parçayı gösterir
    msg.attach(MIMEText(html_to_text(personalized_html), "plain", "utf-8"))
    msg.attach(MIMEText(personalized_html, "html", "utf-8"))
    return msg


def send_all(html_content, recipients, subject=None):
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
                server.sendmail(config.EMAIL_SENDER, email, build_message(html_content, sub, subject).as_string())
                log.info("✓ Başarıyla gönderildi: %s", email)
                time.sleep(1)
            except Exception as e:
                log.error("✗ Hata (%s): %s", email, e)
                failed.append(email)

    sent = len(recipients) - len(failed)
    if failed:
        log.error("[HATA] %d/%d gönderim başarılı, %d başarısız: %s", sent, len(recipients), len(failed),
                  ", ".join(failed))
    else:
        log.info("Tüm gönderimler başarıyla tamamlandı! (%d/%d)", sent, len(recipients))
    return failed
