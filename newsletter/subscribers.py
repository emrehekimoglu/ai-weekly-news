"""Alıcı listeleri: Google Sheets'teki aktif aboneler, yedekler ve önizleme alıcısı."""

import json
import logging
import os

from newsletter import config

try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False

log = logging.getLogger(__name__)


def _read_sheet():
    """Sheets'te durumu 'AKTIF' olan aboneleri, en yeni kayıt geçerli olacak şekilde tekilleştirir."""
    log.info("Google Sheets tablosuna bağlanılıyor...")
    creds = Credentials.from_service_account_info(
        json.loads(config.GCP_SA_KEY), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    rows = gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID).sheet1.get_all_values()

    subscribers = []
    seen = set()
    for row in reversed(rows[1:]):  # en yeni kayıttan eskiye
        if len(row) < 4:
            continue
        email, status, token = row[1].strip().lower(), row[2].strip().upper(), row[3].strip()
        if email in seen:
            continue
        if status == "AKTIF" and "@" in email:
            subscribers.append({"email": email, "token": token})
            seen.add(email)
    return subscribers


def _read_file(path):
    """Satır başına bir e-posta; '#' ile başlayan satırlar yok sayılır."""
    emails = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            email = line.strip().lower()
            if "@" in email and not email.startswith("#") and email not in emails:
                emails.append(email)
    return [{"email": email, "token": ""} for email in emails]


def get_subscribers():
    """Alıcıları ve varsa Sheets hatasını (recipients, error) olarak döndürür.

    Sheets yapılandırılmışken okunamazsa yedeklere (subscribers.txt, EMAIL_RECEIVER) düşülür;
    hata döndürülür ki bülten gönderildikten sonra çalışma hata ile bitsin.
    """
    error = None
    if HAS_GSPREAD and config.GCP_SA_KEY and config.SPREADSHEET_ID:
        try:
            subscribers = _read_sheet()
            if subscribers:
                log.info("✓ Toplam %d TEKİL aktif abone bulundu.", len(subscribers))
                return subscribers, None
            error = "Tabloda 'AKTIF' statüsünde abone bulunamadı"
        except Exception as e:
            error = f"Google Sheets okunamadı: {e}"
        log.error("::error::%s. Bülten yalnızca yedek alıcılara gidecek ve çalışma hata ile bitecek.", error)

    if os.path.exists(config.SUBSCRIBERS_FILE):
        emails = _read_file(config.SUBSCRIBERS_FILE)
        if emails:
            return emails, error
    return ([{"email": config.EMAIL_RECEIVER, "token": ""}] if config.EMAIL_RECEIVER else []), error


def get_preview_recipients():
    """Önizleme alıcısı: yalnızca bülten sahibi. Abone listesine asla bakılmaz."""
    email = config.preview_address()
    return [{"email": email, "token": ""}] if email else []
