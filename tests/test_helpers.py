"""Ağ, LLM veya e-posta gerektirmeyen yardımcı fonksiyon testleri."""

import time

import pytest

import main


def make_valid_html(link_count=main.MIN_DIGEST_CARDS):
    links = "".join(f'<a href="https://example.com/{i}">Haber {i}</a>' for i in range(link_count))
    padding = "<p>" + "x" * 2000 + "</p>"
    return f"<html><body>{links}{padding}</body></html>"


# --- parse_to_turkish_date ---

def test_parse_iso_string():
    assert main.parse_to_turkish_date("2026-09-28T10:00:00Z") == "28 Eylül 2026"


def test_parse_struct_time():
    st = time.strptime("2026-01-05", "%Y-%m-%d")
    assert main.parse_to_turkish_date(st) == "5 Ocak 2026"


@pytest.mark.parametrize("value", [None, "", "dün", "2026-13-45"])
def test_parse_invalid_falls_back(value):
    assert main.parse_to_turkish_date(value) == "Bu Hafta"


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
    assert main.strip_code_fences(raw) == "<html></html>"


# --- validate_digest_html ---

def test_validate_accepts_good_html():
    main.validate_digest_html(make_valid_html())


def test_validate_rejects_short_html():
    with pytest.raises(ValueError, match="kısa"):
        main.validate_digest_html("<html><body></body></html>")


def test_validate_rejects_missing_body():
    html = make_valid_html().replace("<body>", "").replace("</body>", "")
    with pytest.raises(ValueError, match="body"):
        main.validate_digest_html(html)


def test_validate_rejects_too_few_links():
    with pytest.raises(ValueError, match="bağlantı"):
        main.validate_digest_html(make_valid_html(link_count=main.MIN_DIGEST_CARDS - 1))
