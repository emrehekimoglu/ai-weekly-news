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
    turkish: bool = False  # Türk teknoloji basınından ("Türkiye'den" bölümüne aday)

    def to_prompt(self, index):
        """Modele giden ham veri listesindeki tek bir madde."""
        source = f"{self.source} (Türkiye)" if self.turkish else self.source
        return (f"[{index}] Kaynak: {source}\nBaşlık: {self.title}\nYayın Tarihi: {self.date}\n"
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


@dataclass
class Tool:
    """"Haftanın Aracı": GitHub/HN haberlerinden okurun hemen deneyebileceği bir araç veya ipucu."""
    item: NewsItem  # bağlantı ve kaynak buradan alınır
    name: str
    what: str  # ne işe yarar (tek cümle)
    how: str  # hemen denemek için ilk adım


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
    turkiye: list[DigestEntry] = field(default_factory=list)  # "Türkiye'den" bölümü (boşsa atlanır)
    tool: Tool | None = None  # "Haftanın Aracı" (uygun aday yoksa atlanır)
    date: str = field(default_factory=_today)  # sayının Türkçe tarihi
