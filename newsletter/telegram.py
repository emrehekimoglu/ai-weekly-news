"""Telegram kanalı: abonelere gönderilen her sayının kısa özetini ve arşiv bağlantısını kanala yollar.

İş akışı bunu web arşivi adımından sonra `python -m newsletter.telegram` olarak çalıştırır; sadece
gerçek gönderimlerde (önizleme, dry_run ve testlerde değil). TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID
yoksa hiçbir şey yapmadan çıkar. Telegram hatası bülteni başarısız saymaz: uyarı olarak rapora girer,
uyarı e-postası bunu sahibine bildirir.
"""

import argparse
import html
import json
import logging
import sys
import time

import requests

from newsletter import config, history, report
from newsletter.dates import parse_to_turkish_date

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
TITLE = "AI & Teknoloji Radarı"
MAX_POINTS = 5
# GitHub Pages yeni sayfayı genelde 1 dakika içinde yayınlar; bağlantı önizlemesi boş kalmasın diye beklenir
PAGE_WAIT_SECONDS = 240
PAGE_POLL_SECONDS = 15
# Telegram mesaj sınırı 4096 karakter; parçalar kısaltılınca toplam bunun çok altında kalır
MAX_TEXT = 300
MAX_INTRO = 1000


def configured():
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _short(text, limit=MAX_TEXT):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def build_message(summary, url=None, signup_url=None):
    """Sayı özetinden (app.write_post_summary) Telegram HTML mesajı üretir."""
    esc = html.escape
    lines = [f"📡 <b>{esc(TITLE)}</b> • {esc(parse_to_turkish_date(summary.get('date', '')))}", ""]
    if summary.get("headline"):
        lines += [f"<b>{esc(_short(summary['headline']))}</b>", ""]
    if summary.get("intro"):
        lines += [esc(_short(summary["intro"], MAX_INTRO)), ""]
    points = summary.get("tldr") or summary.get("titles") or []
    if points:
        lines += [f"• {esc(_short(p))}" for p in points[:MAX_POINTS]] + [""]
    if url:
        lines.append(f'👉 <a href="{esc(url)}">Sayının tamamını oku</a>')
    if signup_url:
        lines.append(f'✉️ <a href="{esc(signup_url)}">Her pazartesi e-postayla al</a>')
    return "\n".join(lines).strip()


def wait_for_page(url, timeout=PAGE_WAIT_SECONDS, poll=PAGE_POLL_SECONDS):
    """Arşiv sayfası yayına girene kadar bekler; süre dolarsa yine de devam edilir."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            if requests.get(url, timeout=15).status_code == 200:
                return True
        except requests.RequestException:
            pass
        if time.monotonic() >= deadline:
            log.warning("Arşiv sayfası %d sn içinde yayına girmedi; gönderi yine de yapılıyor.", timeout)
            return False
        time.sleep(poll)


def _hide_token(text):
    return str(text).replace(config.TELEGRAM_BOT_TOKEN, "***") if config.TELEGRAM_BOT_TOKEN else str(text)


def send(text, preview_url=None):
    """Kanala mesaj gönderir; hata olursa açıklamasıyla RuntimeError (bot anahtarı gizlenir)."""
    payload = {"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    payload["link_preview_options"] = {"url": preview_url} if preview_url else {"is_disabled": True}
    try:
        r = requests.post(API.format(token=config.TELEGRAM_BOT_TOKEN, method="sendMessage"), json=payload, timeout=30)
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        raise RuntimeError(_hide_token(f"Telegram'a bağlanılamadı ({type(e).__name__})")) from None
    if not data.get("ok"):
        raise RuntimeError(_hide_token(f"Telegram reddetti: {data.get('description', r.status_code)}"))


def post_issue(path=None):
    """Bu çalışmada gönderilen sayıyı kanala yollar. Döndürür: 'skipped', 'posted' veya 'failed'."""
    if not configured():
        log.info("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID yok; Telegram gönderisi atlandı.")
        return "skipped"
    try:
        with open(path or config.POST_FILE, encoding="utf-8") as f:
            summary = json.load(f)
    except (OSError, ValueError):
        log.info("Bu çalışmada abonelere sayı gönderilmedi; Telegram gönderisi atlandı.")
        return "skipped"
    date = summary.get("date", "")
    if history.posted_to_telegram(date):
        log.info("%s sayısı Telegram'a zaten gönderilmişti; tekrar gönderilmedi.", date)
        return "skipped"

    url = config.issue_url(date) if date else None
    if url:
        wait_for_page(url)
    try:
        send(build_message(summary, url, config.SIGNUP_URL), url)
    except RuntimeError as e:
        report.add_warning(f"Sayı Telegram kanalına gönderilemedi: {e}")
        return "failed"
    history.mark_posted(date)
    log.info("Sayı Telegram kanalına gönderildi.")
    return "posted"


def send_test():
    """Kurulumu denemek için kanala kısa bir mesaj atar (iş akışının telegram_test girdisi)."""
    if not configured():
        log.error("::error::TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID secret'larının ikisi de eklenmeli.")
        return 1
    text = (f"📡 <b>{TITLE}</b>\n\nKurulum denemesi: bu kanal artık her pazartesi yeni sayıyı alacak. "
            "Bu mesajı silebilirsiniz.")
    try:
        send(text)
    except RuntimeError as e:
        log.error("::error::%s", e)
        return 1
    log.info("Deneme mesajı Telegram kanalına gönderildi.")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="kanala deneme mesajı gönder")
    args = parser.parse_args(argv)
    if args.test:
        return send_test()
    post_issue()
    return 0  # Telegram sorunu bülten çalışmasını kırmızı yapmaz; uyarı e-postası haber verir


if __name__ == "__main__":
    sys.exit(main())
