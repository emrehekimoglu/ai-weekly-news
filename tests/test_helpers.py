"""Ağ, LLM veya e-posta gerektirmeyen yardımcı fonksiyon testleri."""

import time

import pytest

from newsletter import config
from newsletter.dates import parse_to_turkish_date
from newsletter.llm import build_prompt, strip_code_fences, validate_digest_html
from tests.conftest import make_item


def make_valid_html(link_count=config.MIN_DIGEST_CARDS):
    links = "".join(f'<a href="https://example.com/{i}">Haber {i}</a>' for i in range(link_count))
    padding = "<p>" + "x" * 2000 + "</p>"
    return f"<html><body>{links}{padding}</body></html>"


# --- parse_to_turkish_date ---

def test_parse_iso_string():
    assert parse_to_turkish_date("2026-09-28T10:00:00Z") == "28 Eylül 2026"


def test_parse_struct_time():
    st = time.strptime("2026-01-05", "%Y-%m-%d")
    assert parse_to_turkish_date(st) == "5 Ocak 2026"


@pytest.mark.parametrize("value", [None, "", "dün", "2026-13-45"])
def test_parse_invalid_falls_back(value):
    assert parse_to_turkish_date(value) == "Bu Hafta"


# --- build_prompt ---

def test_prompt_lists_numbered_items():
    prompt = build_prompt([make_item(title="Birinci"), make_item(title="İkinci", link="https://x.test/2")])
    assert "[1] Kaynak: s\nBaşlık: Birinci\n" in prompt
    assert "[2] Kaynak: s\nBaşlık: İkinci\nYayın Tarihi: d\nLink: https://x.test/2\nÖzet: x\n" in prompt


# --- strip_code_fences ---

@pytest.mark.parametrize(
    "raw",
    [
        "```html\n<html></html>\n```",
        "```\n<html></html>\n```",
        "  <html></html>  ",
    ],
)
def test_strip_code_fences(raw):
    assert strip_code_fences(raw) == "<html></html>"


# --- validate_digest_html ---

def test_validate_accepts_good_html():
    validate_digest_html(make_valid_html())


def test_validate_rejects_short_html():
    with pytest.raises(ValueError, match="kısa"):
        validate_digest_html("<html><body></body></html>")


def test_validate_rejects_missing_body():
    html = make_valid_html().replace("<body>", "").replace("</body>", "")
    with pytest.raises(ValueError, match="body"):
        validate_digest_html(html)


def test_validate_rejects_too_few_links():
    with pytest.raises(ValueError, match="bağlantı"):
        validate_digest_html(make_valid_html(link_count=config.MIN_DIGEST_CARDS - 1))
