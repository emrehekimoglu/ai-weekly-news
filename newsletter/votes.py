"""Okur oyları: Worker'ın "Geri Bildirim" sekmesine yazdığı 👍/👎 oylarından haftalık özet ve modele hafif bir ipucu.

Oy satırı: [Zaman, Sayı, Haber, Oy, Okur]. "Sayı" gönderim tarihidir (data/history.json ile aynı),
"Haber" e-postadaki sıradır (1'den başlar, history.json'daki entries sırası; 0 = sayının tamamı).
Önizleme oyları ("onizleme-…") ve geçmişte olmayan sayılar yok sayılır. Okur kimliği (e-postadan
türetilen kısa özet) yalnızca okunur; hiçbir yere yazılmaz.

Okur az, oylar seyrek: ipucu yalnızca yeterli oy varsa verilir ve modelin öncelik kurallarını değiştirmez.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from newsletter import config
from newsletter.dates import parse_to_turkish_date

log = logging.getLogger(__name__)

FEEDBACK_SHEET = "Geri Bildirim"
READ_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
ISSUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MIN_VOTES_FOR_HINT = 3   # son sayılarda en az bu kadar haber oyu yoksa modele ipucu verilmez
MIN_CATEGORY_VOTES = 2   # bir kategori için en az bu kadar oy olmalı
MAX_EXAMPLE_TITLES = 5


@dataclass
class Story:
    issue: str
    number: int
    title: str
    category: str | None
    up: int = 0
    down: int = 0

    @property
    def net(self):
        return self.up - self.down


@dataclass
class Tally:
    stories: list[Story] = field(default_factory=list)  # en az bir oy almış haberler, eskiden yeniye
    issue_votes: dict = field(default_factory=dict)      # {sayı tarihi: [👍, 👎]} (sayının tamamına verilen)

    @property
    def story_votes(self):
        return sum(s.up + s.down for s in self.stories)

    def categories(self):
        """{kategori: [👍, 👎]}; kategorisi bilinmeyen (eski kayıt) haberler sayılmaz."""
        totals = {}
        for s in self.stories:
            if s.category:
                up_down = totals.setdefault(s.category, [0, 0])
                up_down[0] += s.up
                up_down[1] += s.down
        return totals


def tally(rows, issues):
    """Geri Bildirim satırlarını geçmişteki sayılara ve haberlere eşler.

    Geçerli olmayan satırlar (önizleme, bilinmeyen sayı/haber, bozuk değer) sessizce atlanır.
    """
    by_date = {issue.get("date"): issue.get("entries", []) for issue in issues}
    stories, issue_votes = {}, {}
    for row in rows[1:]:
        if len(row) < 4:
            continue
        issue, vote = str(row[1]).strip(), str(row[3]).strip()
        if not ISSUE_RE.match(issue) or issue not in by_date or vote not in ("up", "down"):
            continue
        try:
            number = int(row[2])
        except (TypeError, ValueError):
            continue
        up = vote == "up"
        if number == 0:
            counts = issue_votes.setdefault(issue, [0, 0])
            counts[0 if up else 1] += 1
            continue
        entries = by_date[issue]
        if not 1 <= number <= len(entries):
            continue
        key = (issue, number)
        if key not in stories:
            entry = entries[number - 1]
            stories[key] = Story(issue, number, entry.get("title", ""), entry.get("category"))
        if up:
            stories[key].up += 1
        else:
            stories[key].down += 1
    ordered = [stories[k] for k in sorted(stories)]
    return Tally(stories=ordered, issue_votes=issue_votes)


def reader_hint(t):
    """Modele verilecek kısa okur geri bildirimi; yeterli oy yoksa boş metin."""
    if t.story_votes < MIN_VOTES_FOR_HINT:
        return ""
    liked, disliked = [], []
    for category, (up, down) in t.categories().items():
        if up + down >= MIN_CATEGORY_VOTES and up != down:
            (liked if up > down else disliked).append((up - down, category))
    liked = [c for _, c in sorted(liked, reverse=True)]
    disliked = [c for _, c in sorted(disliked)]
    # En çok beğenilen, eşitlikte en yeni haber önce
    liked_titles = [s.title for s in sorted(t.stories, key=lambda s: (s.net, s.issue), reverse=True)
                    if s.net > 0 and s.title][:MAX_EXAMPLE_TITLES]
    disliked_titles = [s.title for s in sorted(t.stories, key=lambda s: s.net) if s.net < 0 and s.title][:3]
    if not (liked or disliked or liked_titles or disliked_titles):
        return ""

    lines = ["", "OKUR GERİ BİLDİRİMİ (sadece hafif bir ipucu; yukarıdaki öncelik sırası ve önem değerlendirmesi AYNEN geçerli):"]
    if liked:
        lines.append(f"- Okurların daha çok beğendiği türler: {', '.join(liked)}")
    if disliked:
        lines.append(f"- Daha az ilgi gören türler: {', '.join(disliked)}")
    if liked_titles:
        lines.append(f"- Beğenilen haberlerden örnekler: {'; '.join(liked_titles)}")
    if disliked_titles:
        lines.append(f"- Beğenilmeyen haberlerden örnekler: {'; '.join(disliked_titles)}")
    lines.append("Bunu yalnızca benzer önemdeki haberler arasında seçim yaparken ve sıralarken kullan. "
                 "Önemli bir gelişmeyi türü yüzünden ASLA dışarıda bırakma; az beğenilen türleri tamamen çıkarma.")
    return "\n".join(lines) + "\n"


def _mark(up, down):
    return f"👍 {up} / 👎 {down}"


def summary_lines(t, hint):
    """Sahibe giden haftalık oy özeti (düz metin satırları); hiç oy yoksa boş liste."""
    if not (t.stories or t.issue_votes):
        return []
    dates = sorted({s.issue for s in t.stories} | set(t.issue_votes))
    last = dates[-1]
    lines = [f"Son oy alan sayı ({parse_to_turkish_date(last)}):"]
    if last in t.issue_votes:
        lines.append(f"- Sayının tamamı: {_mark(*t.issue_votes[last])}")
    for s in t.stories:
        if s.issue == last:
            lines.append(f"- {s.number}. {s.title}: {_mark(s.up, s.down)}")
    categories = t.categories()
    if categories:
        lines += ["", f"Oy alan {len(dates)} sayıda türlere göre:"]
        for category, (up, down) in sorted(categories.items(), key=lambda kv: kv[1][1] - kv[1][0]):
            lines.append(f"- {category}: {_mark(up, down)}")
    lines.append("")
    if hint:
        lines.append("Bu sayıyı yazarken modele okurların beğendiği türlere hafifçe yönelmesi söylendi.")
    else:
        lines.append(f"Henüz yeterli oy yok (en az {MIN_VOTES_FOR_HINT} haber oyu gerekiyor); "
                     "seçki oylardan etkilenmedi.")
    return lines


def _open_spreadsheet():
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(json.loads(config.GCP_SA_KEY), scopes=[READ_SCOPE])
    return gspread.authorize(creds).open_by_key(config.SPREADSHEET_ID)


def load_rows():
    """Geri Bildirim sekmesinin satırları; Sheets yoksa, sekme yoksa veya okunamazsa boş liste."""
    if not (config.GCP_SA_KEY and config.SPREADSHEET_ID):
        return []
    try:
        from gspread.exceptions import WorksheetNotFound

        try:
            return _open_spreadsheet().worksheet(FEEDBACK_SHEET).get_all_values()
        except WorksheetNotFound:
            return []
    except Exception as e:
        log.warning("Okur oyları okunamadı (%s); bu hafta oylar kullanılmadı.", type(e).__name__)
        return []


def collect(issues):
    """(modele ipucu, sahibe özet satırları); oy yoksa ("", [])."""
    t = tally(load_rows(), issues)
    hint = reader_hint(t)
    if t.stories or t.issue_votes:
        log.info("Okur oyları: %d haber oyu, %d sayı oyu; modele ipucu %s.", t.story_votes,
                 sum(sum(v) for v in t.issue_votes.values()), "verildi" if hint else "verilmedi")
    return hint, summary_lines(t, hint)
