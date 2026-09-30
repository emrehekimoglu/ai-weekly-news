"""Bülteni depodaki Jinja2 şablonlarından HTML ve düz metin olarak üretir."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html.j2"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_html(digest, unsubscribe_url=None):
    return _env.get_template("newsletter.html.j2").render(digest=digest, unsubscribe_url=unsubscribe_url)


def render_text(digest, unsubscribe_url=None):
    return _env.get_template("newsletter.txt.j2").render(digest=digest, unsubscribe_url=unsubscribe_url).strip() + "\n"
