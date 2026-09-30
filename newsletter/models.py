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
