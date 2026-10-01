"""Haftalık abone istatistikleri: her gerçek gönderimde Sheets'teki "Stats" sekmesine bir satır.

Yalnızca toplam sayılar yazılır ve loglanır; hiçbir e-posta adresi sekmeye, loga veya depoya girmez.
Yeni kayıt ve ayrılan sayıları, bir önceki satırdaki toplamlarla karşılaştırılarak bulunur.
"""

import json
import logging
from dataclasses import dataclass

from newsletter import config, subscribers

log = logging.getLogger(__name__)

STATS_SHEET = "Stats"
HEADER = ["Tarih", "Aktif abone", "Yeni kayıt", "Ayrılan", "Net değişim",
          "Gönderilen", "Başarısız", "Kayıtlı e-posta", "Pasif"]
WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


@dataclass
class Counts:
    active: int    # en yeni kaydı AKTIF olan tekil e-posta
    total: int     # tabloda en az bir kez geçen tekil e-posta (yalnızca kayıtla artar)
    inactive: int  # en yeni kaydı AKTIF olmayan tekil e-posta


def count(rows):
    """Abone tablosunun satırlarından tekil e-posta sayıları."""
    latest = subscribers.latest_rows(rows)
    active = sum(1 for status, _ in latest.values() if status == "AKTIF")
    return Counts(active=active, total=len(latest), inactive=len(latest) - active)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def previous_counts(stats_rows):
    """Stats sekmesindeki son geçerli satırın toplamları; yoksa None."""
    for row in reversed(stats_rows[1:]):
        if len(row) >= len(HEADER):
            active, total, inactive = _int(row[1]), _int(row[7]), _int(row[8])
            if None not in (active, total, inactive):
                return Counts(active=active, total=total, inactive=inactive)
    return None


def build_row(date, counts, previous, sent, failed):
    """Sekmeye eklenecek satır. İlk satırda (önceki yok) değişim sütunları boş kalır.

    Yeni kayıt: yeni tekil e-posta sayısı. Ayrılan: pasife geçen sayısı (yeniden abone olanlar düşülür,
    0'ın altına inmez). Net değişim: aktif abone farkı.
    """
    if previous is None:
        new = left = net = ""
    else:
        new = counts.total - previous.total
        left = max(0, counts.inactive - previous.inactive)
        net = counts.active - previous.active
    return [date, counts.active, new, left, net, sent, failed, counts.total, counts.inactive]


def _open_spreadsheet():
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(json.loads(config.GCP_SA_KEY), scopes=[WRITE_SCOPE])
    return gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID)


def _stats_worksheet(spreadsheet):
    from gspread.exceptions import WorksheetNotFound

    try:
        return spreadsheet.worksheet(STATS_SHEET)
    except WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=STATS_SHEET, rows=200, cols=len(HEADER))
        sheet.append_row(HEADER)
        return sheet


def record(date, sent, failed):
    """Gerçek gönderimden sonra istatistik satırını ekler. Hata çalışmayı durdurmaz, sadece uyarır."""
    if not (config.GCP_SA_KEY and config.SPREADSHEET_ID):
        return None
    try:
        spreadsheet = _open_spreadsheet()
        counts = count(spreadsheet.sheet1.get_all_values())
        sheet = _stats_worksheet(spreadsheet)
        row = build_row(date, counts, previous_counts(sheet.get_all_values()), sent, failed)
        sheet.append_row(row)
    except Exception as e:
        log.warning("::warning::Abone istatistikleri kaydedilemedi (%s: %s). Hizmet hesabının tabloda "
                    "Düzenleyici yetkisi olmalı. Bülten gönderimi etkilenmedi.", type(e).__name__, e)
        return None
    log.info("İstatistik: %d aktif abone, yeni kayıt %s, ayrılan %s, net %s.",
             counts.active, row[2] if row[2] != "" else "-", row[3] if row[3] != "" else "-",
             row[4] if row[4] != "" else "-")
    return row
