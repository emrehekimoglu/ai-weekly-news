"""Tarihleri Türkçe gösterime çeviren yardımcılar."""

from datetime import datetime

MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


def parse_to_turkish_date(value):
    """struct_time veya 'YYYY-MM-DD...' metnini '28 Eylül 2026' biçimine çevirir; olmazsa 'Bu Hafta'."""
    try:
        if hasattr(value, "tm_year"):
            return f"{value.tm_mday} {MONTHS[value.tm_mon - 1]} {value.tm_year}"
        if isinstance(value, str) and len(value) >= 10:
            dt = datetime.strptime(value[:10], "%Y-%m-%d")
            return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}"
    except Exception:
        pass
    return "Bu Hafta"
