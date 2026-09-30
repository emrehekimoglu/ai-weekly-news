"""Kaynaklardan toplanan haberlerin ortak veri yapısı."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from newsletter.dates import parse_to_turkish_date


@dataclass
class NewsItem:
    source: str
    title: str
    date: str  # Türkçe, örn. "28 Eylül 2026"
    link: str
    summary: str

    def to_prompt(self, index):
        """Modele giden ham veri listesindeki tek bir madde."""
        return (f"[{index}] Kaynak: {self.source}\nBaşlık: {self.title}\nYayın Tarihi: {self.date}\n"
                f"Link: {self.link}\nÖzet: {self.summary}\n")


@dataclass
class DigestEntry:
    """Bültende yer alan tek bir haber: kaynak öğe + modelin yazdığı Türkçe başlık, kategori ve özet."""
    item: NewsItem
    title: str
    category: str
    summary: str


@dataclass
class Stat:
    """"Haftanın Rakamı": haberlerden birindeki çarpıcı sayı ve ne anlama geldiği."""
    value: str  # örn. "10 GW", "%40"
    label: str


def _today():
    return parse_to_turkish_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))


@dataclass
class Digest:
    intro: str  # "Haftanın Özeti" (2 cümle)
    entries: list[DigestEntry]
    # Kapak alanları isteğe bağlı: model vermezse şablon bu bölümleri atlar
    headline: str | None = None  # haftanın manşeti, konu satırında da kullanılır
    tldr: list[str] = field(default_factory=list)  # "30 saniyede bu hafta" maddeleri
    stat: Stat | None = None
    date: str = field(default_factory=_today)  # sayının Türkçe tarihi
