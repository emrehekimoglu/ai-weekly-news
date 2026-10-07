"""Gönderilen bültenleri GitHub Pages için statik bir web arşivine ekler.

Kullanım: python archive.py <bülten.html> <site_klasörü> [YYYY-AA-GG]
         python archive.py --rebuild <site_klasörü>   (yeni sayı eklemeden index ve RSS'i yeniler)

Site klasörü gh-pages dalının çalışma kopyasıdır. Bülten issues/<tarih>.html olarak
yazılır, ardından index.html ve feed.xml (RSS) tüm sayılardan yeniden üretilir. Yayınlanmadan önce
iptal bağlantıları, token içeren adresler, script'ler ve olay öznitelikleri silinir;
böylece hiçbir abone bilgisi web'e çıkmaz.
"""

import html
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import quote, urlparse

from newsletter import config

SITE_TITLE = "AI & Teknoloji Radarı Arşivi"
SITE_DESCRIPTION = "Yapay zekâ ve teknoloji dünyasında haftanın öne çıkanları, her Pazartesi Türkçe."
ISSUES_DIR = "issues"
FEED_FILE = "feed.xml"
FEED_ITEMS = 20
TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Aboneye özel veri taşıyabilecek bağlantılar (iptal, oy, token, e-posta parametresi, mailto)
_PERSONAL_HREF = re.compile(r"(action=(unsubscribe|vote)|[?&](token|email)=|^mailto:)", re.IGNORECASE)
_ANCHOR = re.compile(r"<a\b[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)
_HREF = re.compile(r"""href\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)
# Eski Google Form abonelik bağlantıları (SIGNUP_URL artık Worker'ın /abone sayfası)
_LEGACY_SIGNUP_HREF = re.compile(r"""href=(["'])https://(forms\.gle/|docs\.google\.com/forms/)[^"']*\1""",
                                 re.IGNORECASE)
# Bülten şablonundaki manşet ve gizli önizleme metni (RSS ve index için)
_HEADLINE = re.compile(r"""<td\b[^>]*class="[^"]*\bheadline\b[^"]*"[^>]*>(.*?)</td>""", re.IGNORECASE | re.DOTALL)
_PREHEADER = re.compile(r"""<div\b[^>]*display:\s*none[^>]*>(.*?)</div>""", re.IGNORECASE | re.DOTALL)


def turkish_date(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.day} {TR_MONTHS[d.month - 1]} {d.year}"


def _strip_personal_link(match):
    tag = match.group(0)
    href = _HREF.search(tag)
    if href and _PERSONAL_HREF.search(html.unescape(href.group(2)).strip()):
        return ""
    return tag


def sanitize(content):
    """Web'de yayınlanacak bültenden kişisel ve çalıştırılabilir içeriği temizler."""
    # E-posta altbilgisi (build_message) arşive girmemeli; varsa hr'den itibaren sil
    content = re.sub(r"<hr[^>]*>\s*<p[^>]*>\s*Bu bülteni AI &(amp;)? Teknoloji Radarı'na abone.*?</p>",
                     "", content, flags=re.IGNORECASE | re.DOTALL)
    content = _ANCHOR.sub(_strip_personal_link, content)
    content = re.sub(r"<script\b.*?</script\s*>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<(script|iframe|object|embed)\b[^>]*>", "", content, flags=re.IGNORECASE)
    content = re.sub(r"""\s+on[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", "", content, flags=re.IGNORECASE)
    content = re.sub(r"""(href|src)\s*=\s*(["'])\s*javascript:[^"']*\2""", r'\1="#"', content,
                     flags=re.IGNORECASE)
    return content


def _feed_url():
    return f"{config.ARCHIVE_URL.rstrip('/')}/{FEED_FILE}" if config.ARCHIVE_URL else None


def _head(title, url=None, feed=None):
    head = (f'<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{html.escape(title)}</title>\n")
    if feed:
        # Tarayıcılar ve RSS okuyucular beslemeyi bu satırdan otomatik bulur
        head += f'<link rel="alternate" type="application/rss+xml" title="{html.escape(SITE_TITLE)}" href="{feed}">\n'

    if url:
        # Paylaşılan bağlantının sosyal medyada başlıkla görünmesi için Open Graph
        head += (f'<meta property="og:type" content="article">\n<meta property="og:title" content="{html.escape(title)}">\n'
                 f'<meta property="og:url" content="{html.escape(url)}">\n')
    return head


_LINK_STYLE = "color: #2563eb; text-decoration: none; margin-right: 14px; white-space: nowrap;"


def _signup_link():
    if not config.SIGNUP_URL:
        return ""
    return (f'<a href="{html.escape(config.SIGNUP_URL)}" style="color: #2563eb; font-weight: 600; text-decoration: none;">'
            "Ücretsiz abone olun →</a>")


def _is_signup_page():
    """SIGNUP_URL bültenin kendi /abone sayfasıysa e-posta doğrudan oraya POST edilebilir."""
    return (urlparse(config.SIGNUP_URL).path.rstrip("/").endswith("/abone")
            and not _is_legacy_signup(config.SIGNUP_URL))


def _is_legacy_signup(url):
    return bool(_LEGACY_SIGNUP_HREF.search(f'href="{url}"'))


# Kutu hem index'te hem sayı sayfalarında (e-posta CSS'i olan) kullanıldığı için kendi stilini taşır
_SIGNUP_STYLE = """<style>
  .radar-signup { max-width: 620px; margin: 0 auto 24px auto; padding: 20px 22px; box-sizing: border-box;
                  background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 12px; color: #0f172a;
                  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
  .radar-signup h2 { font-size: 18px; margin: 0 0 6px 0; }
  .radar-signup p { font-size: 14px; line-height: 21px; color: #475569; margin: 0 0 14px 0; }
  .radar-signup form { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; }
  .radar-signup input[type=email] { flex: 1 1 200px; min-width: 0; padding: 11px 12px; font-size: 16px;
                                    border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; color: #0f172a; }
  .radar-signup button, .radar-signup .btn { padding: 11px 18px; font-size: 15px; font-weight: 600; border: 0;
                  border-radius: 8px; background: #2563eb; color: #fff; cursor: pointer; text-decoration: none; }
  .radar-signup .hp { position: absolute; left: -9999px; }
  .radar-signup .alt { margin: 12px 0 0 0; font-size: 13px; }
  .radar-signup .alt a { color: #2563eb; text-decoration: none; }
  @media (prefers-color-scheme: dark) {
    .radar-signup { background: #1e293b; border-color: #334155; color: #e2e8f0; }
    .radar-signup p { color: #94a3b8; }
    .radar-signup input[type=email] { background: #0f172a; border-color: #475569; color: #e2e8f0; }
    .radar-signup .alt a { color: #60a5fa; }
  }
</style>"""


def signup_box():
    """Abone olma kutusu (+ RSS bağlantısı): /abone sayfasına doğrudan form, başka bir adresse düğme.

    SIGNUP_URL ve arşiv adresi yoksa boş."""
    feed = _feed_url()
    if not config.SIGNUP_URL and not feed:
        return ""
    parts = [_SIGNUP_STYLE, '<section class="radar-signup">']
    if config.SIGNUP_URL:
        url = html.escape(config.SIGNUP_URL)
        parts.append("<h2>Her Pazartesi e-postanızda</h2>\n<p>Haftanın en önemli yapay zekâ ve teknoloji "
                     "haberleri, birkaç dakikada okunacak Türkçe bir özetle. Ücretsiz.</p>")
        if _is_signup_page():
            # Worker'daki formla aynı alanlar: email ve botlar için gizli "website" tuzağı
            parts.append(f'<form method="post" action="{url}">'
                         '<input type="email" name="email" required maxlength="254" autocomplete="email"'
                         ' placeholder="e-posta@adresiniz.com" aria-label="E-posta adresiniz">'
                         '<input class="hp" type="text" name="website" tabindex="-1" autocomplete="off"'
                         ' aria-hidden="true"><button type="submit">Abone ol</button></form>')
        else:
            parts.append(f'<a class="btn" href="{url}">Ücretsiz abone olun →</a>')
    if feed:
        parts.append(f'<p class="alt">E-posta istemiyor musunuz? <a href="{html.escape(feed)}">RSS ile takip edin</a></p>')
    parts.append("</section>")
    return "\n".join(parts)


def _refresh_signup_links(content):
    """Eski sayfalardaki Google Form bağlantılarını güncel SIGNUP_URL ile değiştirir."""
    if not config.SIGNUP_URL or _is_legacy_signup(config.SIGNUP_URL):
        return content
    return _LEGACY_SIGNUP_HREF.sub(lambda m: f'href="{html.escape(config.SIGNUP_URL)}"', content)


def _plain(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def issue_summary(site_dir, date_str):
    """Arşivdeki sayının manşeti ve kısa özeti (bulunamazsa boş)."""
    try:
        with open(os.path.join(site_dir, ISSUES_DIR, f"{date_str}.html"), encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return "", ""
    headline, preheader = _HEADLINE.search(content), _PREHEADER.search(content)
    return (_plain(headline.group(1)) if headline else "", _plain(preheader.group(1)) if preheader else "")


def share_bar(title, date_str):
    """Sayfanın herkese açık adresini paylaşan bağlantılar (abone verisi içermez). Arşiv adresi yoksa boş."""
    url = config.issue_url(date_str)
    if not url:
        return ""
    u, t = quote(url, safe=""), quote(title, safe="")
    targets = [
        ("X", f"https://twitter.com/intent/tweet?url={u}&text={t}"),
        ("LinkedIn", f"https://www.linkedin.com/sharing/share-offsite/?url={u}"),
        ("WhatsApp", f"https://wa.me/?text={quote(f'{title} {url}', safe='')}"),
        ("Telegram", f"https://t.me/share/url?url={u}&text={t}"),
        ("E-posta", f"mailto:?subject={t}&body={u}"),
    ]
    links = "".join(f'<a href="{html.escape(href)}" target="_blank" rel="noopener" style="{_LINK_STYLE}">{name}</a>'
                    for name, href in targets)
    return ('<p style="max-width: 620px; margin: 0 auto 32px auto; padding: 0 16px; font-family: sans-serif; font-size: 14px;">'
            f'<strong>Paylaş:</strong>&nbsp; {links}</p>')


def render_issue(content, date_str):
    """Temizlenmiş bülteni başlık, viewport ve arşive dönüş bağlantısıyla sarar."""
    content = sanitize(content)
    title = f"{SITE_TITLE} • {turkish_date(date_str)}"
    signup = _signup_link()
    nav = ('<p style="max-width: 720px; margin: 0 auto 16px auto; font-family: sans-serif; font-size: 14px;">'
           '<a href="../index.html" style="color: #2563eb; text-decoration: none;">← Tüm sayılar</a>'
           + (f'<span style="float: right;">{signup}</span>' if signup else "") + "</p>")
    box = signup_box()
    # Sayı sayfasında gövde kenardan kenara; kutu telefonda kenarlara yapışmasın
    share = (f'<div style="padding: 0 16px;">\n{box}\n</div>\n' if box else "") + share_bar(title, date_str)
    page_url = config.issue_url(date_str)

    # <head> içindeki eski title'ı at, kendi meta/title'ımızı ekle
    content = re.sub(r"<title\b.*?</title\s*>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<meta\s+charset[^>]*>", "", content, flags=re.IGNORECASE)
    if re.search(r"<head\b[^>]*>", content, re.IGNORECASE):
        content = re.sub(r"(<head\b[^>]*>)", lambda m: m.group(1) + "\n" + _head(title, page_url), content,
                         count=1, flags=re.IGNORECASE)
    else:
        content = re.sub(r"(<html\b[^>]*>)", lambda m: f"{m.group(1)}\n<head>\n{_head(title, page_url)}</head>", content,
                         count=1, flags=re.IGNORECASE)
    content = re.sub(r"(<body\b[^>]*>)", lambda m: m.group(1) + "\n" + nav, content, count=1, flags=re.IGNORECASE)
    if share.strip():
        content = re.sub(r"(</body\s*>)", lambda m: share + "\n" + m.group(1), content, count=1, flags=re.IGNORECASE)
    if not content.lstrip().lower().startswith("<!doctype"):
        content = "<!DOCTYPE html>\n" + content
    return content


def list_issues(site_dir):
    folder = os.path.join(site_dir, ISSUES_DIR)
    if not os.path.isdir(folder):
        return []
    dates = [name[:-5] for name in os.listdir(folder) if name.endswith(".html") and DATE_RE.match(name[:-5])]
    return sorted(dates, reverse=True)


def render_index(dates, site_dir=None):
    if dates:
        rows = []
        for d in dates:
            headline, _ = issue_summary(site_dir, d) if site_dir else ("", "")
            label = (f'<span class="date">{html.escape(turkish_date(d))}</span>{html.escape(headline)}' if headline
                     else html.escape(turkish_date(d)))
            rows.append(f'    <li><a href="{ISSUES_DIR}/{d}.html">{label}</a></li>')
        body = '  <ul class="issues">\n' + "\n".join(rows) + "\n  </ul>"
    else:
        body = "  <p>Henüz yayınlanmış sayı yok.</p>"
    feed = _feed_url()
    rss = f' • <a href="{html.escape(feed)}" style="color: inherit;">RSS</a>' if feed else ""
    box = signup_box()
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
{_head(SITE_TITLE, feed=feed)}<style>
  :root {{ color-scheme: light dark; --bg: #f8fafc; --card: #ffffff; --text: #0f172a; --muted: #64748b;
           --line: #e2e8f0; --link: #2563eb; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --muted: #94a3b8; --line: #334155; --link: #60a5fa; }}
  }}
  body {{ margin: 0; padding: 32px 16px; background: var(--bg); color: var(--text);
         font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
  main {{ max-width: 640px; margin: 0 auto; }}
  h1 {{ font-size: 26px; margin: 0 0 4px 0; }}
  .sub {{ color: var(--muted); font-size: 14px; margin: 0 0 24px 0; }}
  .issues {{ list-style: none; padding: 0; margin: 0; }}
  .issues li {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; margin-bottom: 10px; }}
  .issues a {{ display: block; padding: 14px 18px; color: var(--link); text-decoration: none; font-weight: 600; }}
  .issues .date {{ display: block; color: var(--muted); font-size: 13px; font-weight: 400; margin-bottom: 2px; }}
</style>
</head>
<body>
<main>
  <h1>🤖 AI & Teknoloji Radarı</h1>
  <p class="sub">Haftalık bültenin geçmiş sayıları • {len(dates)} sayı{rss}</p>
{box}
{body}
</main>
</body>
</html>
"""


def _rfc822(date_str):
    # Gönderim Pazartesi 03:00 UTC civarı; RSS okuyucular için o günün sabahı yeterince doğru
    return format_datetime(datetime.strptime(date_str, "%Y-%m-%d").replace(hour=6, tzinfo=timezone.utc))


def render_feed(dates, site_dir):
    """Son sayıların RSS 2.0 beslemesi. Mutlak adres gerektiği için arşiv adresi yoksa None."""
    feed = _feed_url()
    if not feed:
        return None
    esc = lambda text: html.escape(text, quote=False)  # noqa: E731
    items = []
    for d in dates[:FEED_ITEMS]:
        headline, summary = issue_summary(site_dir, d)
        link = config.issue_url(d)
        title = f"{headline} ({turkish_date(d)})" if headline else f"AI & Teknoloji Radarı • {turkish_date(d)}"
        items.append(f"""  <item>
    <title>{esc(title)}</title>
    <link>{esc(link)}</link>
    <guid isPermaLink="true">{esc(link)}</guid>
    <pubDate>{_rfc822(d)}</pubDate>
    <description>{esc(summary)}</description>
  </item>""")
    home = config.ARCHIVE_URL.rstrip("/") + "/"
    built = _rfc822(dates[0]) if dates else format_datetime(datetime.now(timezone.utc))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{esc("AI & Teknoloji Radarı")}</title>
  <link>{esc(home)}</link>
  <atom:link href="{html.escape(feed)}" rel="self" type="application/rss+xml"/>
  <description>{esc(SITE_DESCRIPTION)}</description>
  <language>tr</language>
  <lastBuildDate>{built}</lastBuildDate>
{chr(10).join(items)}
</channel>
</rss>
"""


def rebuild(site_dir):
    """index.html ve feed.xml'i yeniden yazar, eski sayfalardaki Google Form bağlantılarını günceller."""
    dates = list_issues(site_dir)
    for d in dates:
        path = os.path.join(site_dir, ISSUES_DIR, f"{d}.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        refreshed = _refresh_signup_links(content)
        if refreshed != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(refreshed)
    with open(os.path.join(site_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(dates, site_dir))
    feed = render_feed(dates, site_dir)
    if feed:
        with open(os.path.join(site_dir, FEED_FILE), "w", encoding="utf-8") as f:
            f.write(feed)
    # Jekyll işlemesini kapat: dosyalar olduğu gibi sunulsun
    open(os.path.join(site_dir, ".nojekyll"), "w").close()


def publish(issue_path, site_dir, date_str=None):
    """Bülteni site klasörüne ekler ve index'i yeniden yazar. Yazılan sayfanın yolunu döndürür."""
    date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not DATE_RE.match(date_str):
        raise ValueError(f"Geçersiz tarih: {date_str}")
    with open(issue_path, encoding="utf-8") as f:
        content = f.read()

    os.makedirs(os.path.join(site_dir, ISSUES_DIR), exist_ok=True)
    page = os.path.join(site_dir, ISSUES_DIR, f"{date_str}.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write(render_issue(content, date_str))
    rebuild(site_dir)
    return page


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--rebuild":
        rebuild(sys.argv[2])
        print(f"Arşiv yenilendi: {sys.argv[2]}")
        sys.exit(0)
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(2)
    written = publish(*sys.argv[1:])
    print(f"Arşiv sayfası yazıldı: {written}")
