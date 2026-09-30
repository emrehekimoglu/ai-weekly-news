"""Kaynaklardan toplanan haberlerin ortak veri yapısı."""

from dataclasses import dataclass


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
class Digest:
    intro: str  # "Haftanın Özeti" (2 cümle)
    entries: list[DigestEntry]
