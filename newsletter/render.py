"""Bülteni depodaki Jinja2 şablonlarından HTML ve düz metin olarak üretir."""

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from newsletter import config

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html.j2"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _links():
    """Abone olmayanlara da gösterilebilen ortak bağlantılar: abonelik formu ve bu sayının arşiv sayfası.
    Arşiv sayfası, gönderimle aynı gün (UTC) archive.py tarafından bu tarihle yazılır."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {"signup_url": config.SIGNUP_URL or None, "web_url": config.issue_url(today)}


# feedback_url(story, vote) -> 👍/👎 bağlantısı; verilmezse (arşiv, önizleme dosyası) oy bağlantıları çıkmaz.
def render_html(digest, unsubscribe_url=None, feedback_url=None):
    return _env.get_template("newsletter.html.j2").render(digest=digest, unsubscribe_url=unsubscribe_url,
                                                          feedback_url=feedback_url, **_links())


def render_text(digest, unsubscribe_url=None, feedback_url=None):
    text = _env.get_template("newsletter.txt.j2").render(digest=digest, unsubscribe_url=unsubscribe_url,
                                                         feedback_url=feedback_url, **_links())
    return text.strip() + "\n"
