"""Ortam değişkenlerinden (GitHub Secrets) okunan ayarlar ve başlangıç kontrolü.

Diğer modüller değerleri `config.AD` şeklinde okur, böylece testler tek yerden değiştirebilir.
"""

import json
import os

OPENCODE_API_KEY = os.environ.get("OPENCODE_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

GCP_SA_KEY = os.environ.get("GCP_SA_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
WEB_APP_URL = os.environ.get("WEB_APP_URL", "")
MODEL_NAME = os.environ.get("OPENCODE_MODEL", "deepseek-v4.1-flash")
# Ana model tüm denemelerde başarısız olursa bu model denenir (aynıysa veya boşsa yedek yok)
FALLBACK_MODEL_NAME = os.environ.get("OPENCODE_FALLBACK_MODEL", "qwen3.8-max").strip()
# Opsiyonel: abonelik sayfası (Worker'ın /abone sayfası veya Google Forms). Boşsa "arkadaşına ilet / abone ol" bloğu gösterilmez.
SIGNUP_URL = os.environ.get("SIGNUP_URL", "").strip()


def _default_archive_url():
    # GitHub Actions'ta GITHUB_REPOSITORY "sahip/depo" olur; Pages adresi bundan çıkar
    owner, _, repo = os.environ.get("GITHUB_REPOSITORY", "").partition("/")
    return f"https://{owner.lower()}.github.io/{repo}/" if owner and repo else ""


# Web arşivinin kök adresi (GitHub Pages). Boşsa e-postada "web'de oku" ve arşivde paylaşım bağlantıları çıkmaz.
ARCHIVE_URL = os.environ.get("ARCHIVE_URL", "").strip() or _default_archive_url()

# LLM çağrısı için yeniden deneme ayarları
LLM_MAX_ATTEMPTS = 3
LLM_BACKOFF_SECONDS = 10  # 10s, 20s, ...
# Tek bir model yanıtı için bekleme süresi. qwen3.8-max bu bülten için 300-335 sn sürüyor;
# daha kısa süre, sunucuda tamamlanıp ücretlendirilen yanıtı boşa atıp tekrar istemek demek.
LLM_TIMEOUT_SECONDS = 600
MIN_DIGEST_CARDS = 5

# Opsiyonel: Reddit uygulama kimlik bilgileri (yoksa birleşik RSS akışı kullanılır)
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET")
# "true" ise sadece veri toplanır; model çağrılmaz, e-posta gönderilmez
DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
# "true" ise bülten tam üretilir ama sadece sahibine (PREVIEW_EMAIL, yoksa EMAIL_RECEIVER) gönderilir
PREVIEW = os.environ.get("PREVIEW", "").lower() == "true"
# İş akışının "preview_to" girdisi (ör. mail-tester.com adresi) bu çalışma için PREVIEW_EMAIL'in yerine geçer
PREVIEW_EMAIL = os.environ.get("PREVIEW_TO", "").strip() or os.environ.get("PREVIEW_EMAIL")
# Zamanlanmış (cron) çalışma mı? Yedek zamanlama, bu hafta otomatik gönderilmiş sayıyı tekrar göndermez.
SCHEDULED = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
# İş akışının "fallback_test" girdisi: ana model bilerek bozulur ve önizlemeyi yedek model yazar (sadece sahibine gider)
FALLBACK_TEST = os.environ.get("FALLBACK_TEST", "").lower() == "true"
if FALLBACK_TEST:
    MODEL_NAME = "olmayan-model-yedek-testi"
    PREVIEW = True
PREVIEW_FILE = "newsletter.html"
# Abonelere gönderilen bülten (kişisel iptal bağlantısı olmadan); iş akışı bunu
# GitHub Pages arşivine ekler (archive.py). Önizleme ve DRY_RUN bu dosyayı yazmaz.
ARCHIVE_FILE = "issue.html"
# Aynı sayının Telegram gönderisi için kısa özeti (manşet, özet, maddeler); sadece gerçek gönderimde yazılır
POST_FILE = "issue.json"

# Opsiyonel: her gerçek sayıyı bir Telegram kanalına da gönder (newsletter/telegram.py). İkisi de yoksa adım atlanır.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

SUBSCRIBERS_FILE = "subscribers.txt"

# Kaynak sayıları ve uyarılar; iş akışının son adımı (python -m newsletter.alert) bunu okur
REPORT_FILE = "run_report.json"
# Uyarı e-postasının alıcısı: ALERT_EMAIL, yoksa PREVIEW_EMAIL, yoksa gönderen adres (kendine)
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "").strip()

# Gönderilen sayıların kaydı; iş akışı bu dosyayı depoya commit eder
HISTORY_FILE = "data/history.json"
HISTORY_ISSUES = 8  # bu kadar sayı geriye bakılır

# feedparser.parse(url) zaman aşımı desteklemez; RSS/Atom akışları requests ile bu sürede çekilir
FEED_TIMEOUT_SECONDS = 15


def issue_url(date_str):
    """Verilen tarihli (YYYY-AA-GG) sayının arşiv sayfası adresi; arşiv adresi yoksa None."""
    if not ARCHIVE_URL:
        return None
    return f"{ARCHIVE_URL.rstrip('/')}/issues/{date_str}.html"


def preview_address():
    """Önizleme alıcısı: PREVIEW_EMAIL, yoksa EMAIL_RECEIVER (geçerli değilse None)."""
    email = (PREVIEW_EMAIL or EMAIL_RECEIVER or "").strip()
    return email if "@" in email else None


def check_config():
    """Gönderim için gereken ayarları kontrol eder, eksik/hatalı olanların açıklamalarını döndürür."""
    problems = [f"{name} tanımlı değil" for name, value in [
        ("OPENCODE_API_KEY", OPENCODE_API_KEY),
        ("EMAIL_SENDER", EMAIL_SENDER),
        ("EMAIL_PASSWORD", EMAIL_PASSWORD),
    ] if not value]
    if bool(GCP_SA_KEY) != bool(SPREADSHEET_ID):
        problems.append("GCP_SA_KEY ve SPREADSHEET_ID birlikte tanımlanmalı")
    if GCP_SA_KEY:
        try:
            json.loads(GCP_SA_KEY)
        except ValueError:
            problems.append("GCP_SA_KEY geçerli bir JSON değil")
    if PREVIEW:
        if not preview_address():
            problems.append("Önizleme alıcısı yok (PREVIEW_EMAIL veya EMAIL_RECEIVER)")
    elif not (GCP_SA_KEY and SPREADSHEET_ID) and not EMAIL_RECEIVER and not os.path.exists(SUBSCRIBERS_FILE):
        problems.append("Alıcı kaynağı yok (GCP_SA_KEY + SPREADSHEET_ID, EMAIL_RECEIVER veya subscribers.txt)")
    return problems
