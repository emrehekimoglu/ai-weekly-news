"""Gönderilen bültenleri GitHub Pages için statik bir web arşivine ekler.

Kullanım: python archive.py <bülten.html> <site_klasörü> [YYYY-AA-GG]

Site klasörü gh-pages dalının çalışma kopyasıdır. Bülten issues/<tarih>.html olarak
yazılır, ardından index.html tüm sayılardan yeniden üretilir. Yayınlanmadan önce
iptal bağlantıları, token içeren adresler, script'ler ve olay öznitelikleri silinir;
böylece hiçbir abone bilgisi web'e çıkmaz.
"""

import html
import os
import re
import sys
from datetime import datetime, timezone

SITE_TITLE = "AI & Teknoloji Radarı Arşivi"
ISSUES_DIR = "issues"
TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Aboneye özel veri taşıyabilecek bağlantılar (iptal, token, e-posta parametresi, mailto)
_PERSONAL_HREF = re.compile(r"(action=unsubscribe|[?&](token|email)=|^mailto:)", re.IGNORECASE)
_ANCHOR = re.compile(r"<a\b[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)
_HREF = re.compile(r"""href\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)


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


def _head(title):
    return (f'<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{html.escape(title)}</title>\n")


def render_issue(content, date_str):
    """Temizlenmiş bülteni başlık, viewport ve arşive dönüş bağlantısıyla sarar."""
    content = sanitize(content)
    title = f"{SITE_TITLE} • {turkish_date(date_str)}"
    nav = ('<p style="max-width: 720px; margin: 0 auto 16px auto; font-family: sans-serif; font-size: 14px;">'
           '<a href="../index.html" style="color: #2563eb; text-decoration: none;">← Tüm sayılar</a></p>')

    # <head> içindeki eski title'ı at, kendi meta/title'ımızı ekle
    content = re.sub(r"<title\b.*?</title\s*>", "", content, flags=re.IGNORECASE | re.DOTALL)
    if re.search(r"<head\b[^>]*>", content, re.IGNORECASE):
        content = re.sub(r"(<head\b[^>]*>)", lambda m: m.group(1) + "\n" + _head(title), content,
                         count=1, flags=re.IGNORECASE)
    else:
        content = re.sub(r"(<html\b[^>]*>)", lambda m: f"{m.group(1)}\n<head>\n{_head(title)}</head>", content,
                         count=1, flags=re.IGNORECASE)
    content = re.sub(r"(<body\b[^>]*>)", lambda m: m.group(1) + "\n" + nav, content, count=1, flags=re.IGNORECASE)
    if not content.lstrip().lower().startswith("<!doctype"):
        content = "<!DOCTYPE html>\n" + content
    return content


def list_issues(site_dir):
    folder = os.path.join(site_dir, ISSUES_DIR)
    if not os.path.isdir(folder):
        return []
    dates = [name[:-5] for name in os.listdir(folder) if name.endswith(".html") and DATE_RE.match(name[:-5])]
    return sorted(dates, reverse=True)


def render_index(dates):
    if dates:
        items = "\n".join(
            f'    <li><a href="{ISSUES_DIR}/{d}.html">{html.escape(turkish_date(d))}</a></li>' for d in dates)
        body = f'  <ul class="issues">\n{items}\n  </ul>'
    else:
        body = "  <p>Henüz yayınlanmış sayı yok.</p>"
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
{_head(SITE_TITLE)}<style>
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
</style>
</head>
<body>
<main>
  <h1>🤖 AI & Teknoloji Radarı</h1>
  <p class="sub">Haftalık bültenin geçmiş sayıları • {len(dates)} sayı</p>
{body}
</main>
</body>
</html>
"""


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
    with open(os.path.join(site_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(list_issues(site_dir)))
    # Jekyll işlemesini kapat: dosyalar olduğu gibi sunulsun
    open(os.path.join(site_dir, ".nojekyll"), "w").close()
    return page


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(2)
    written = publish(*sys.argv[1:])
    print(f"Arşiv sayfası yazıldı: {written}")
