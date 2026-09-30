"""E-posta biçimi: şablon, tarihli konu, düz metin sürümü ve iptal başlığı (ağ yok)."""

from datetime import datetime, timezone
from email import message_from_string

import pytest

from newsletter import mailer
from newsletter.render import render_html, render_text
from tests.conftest import make_digest

UNSUB = "https://script.example.com/exec?action=unsubscribe&email=a%40example.com&token=t"


@pytest.fixture(autouse=True)
def env(set_config):
    set_config(EMAIL_SENDER="sender@example.com", WEB_APP_URL="https://script.example.com/exec")


def test_subject_contains_turkish_date():
    subject = mailer.newsletter_subject(datetime(2026, 9, 28, tzinfo=timezone.utc))
    assert subject.endswith("• 28 Eylül 2026")


def test_html_template_has_header_cards_and_footer():
    html = render_html(make_digest(), UNSUB)
    assert "AI &amp; TEKNOLOJİ RADARI" in html
    assert "Haftanın özeti." in html
    assert html.count("Kaynağa Git →") == 5
    assert 'href="https://example.com/3"' in html
    assert "📅 28 Eylül 2026" in html
    assert 'href="https://script.example.com/exec?action=unsubscribe&amp;email=a%40example.com&amp;token=t"' in html
    assert "<img" not in html and "flaticon" not in html


def test_html_template_escapes_model_text():
    digest = make_digest()
    digest.entries[0].summary = '<script>alert(1)</script> & "tırnak"'
    html = render_html(digest)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="#"' in html  # iptal bağlantısı yoksa


def test_text_template():
    text = render_text(make_digest(), UNSUB)
    assert text.startswith("AI & TEKNOLOJİ RADARI\n")
    assert "1. Haber 1\n📅 28 Eylül 2026 • Yeni Model\nÖzet 1.\nKaynağa Git → https://example.com/1\n" in text
    assert "<" not in text
    assert f"Abonelikten ayrılmak için: {UNSUB}" in text
    assert "Abonelikten ayrılmak için" not in render_text(make_digest())


def test_unsubscribe_url_needs_web_app_and_token(set_config):
    assert mailer.unsubscribe_url("a+b@example.com", "") is None
    assert mailer.unsubscribe_url("a+b@example.com", "t") == (
        "https://script.example.com/exec?action=unsubscribe&email=a%2Bb%40example.com&token=t"
    )
    set_config(WEB_APP_URL="")
    assert mailer.unsubscribe_url("a@example.com", "t") is None


def test_message_has_plain_html_and_list_unsubscribe():
    msg = mailer.build_message(make_digest(), {"email": "a@example.com", "token": "t"}, "Konu")
    parsed = message_from_string(msg.as_string())
    assert parsed["List-Unsubscribe"] == f"<{UNSUB}>"
    parts = parsed.get_payload()
    assert [p.get_content_type() for p in parts] == ["text/plain", "text/html"]
    plain = parts[0].get_payload(decode=True).decode("utf-8")
    html = parts[1].get_payload(decode=True).decode("utf-8")
    assert "Haftanın özeti." in plain
    assert UNSUB in plain
    assert 'href="https://script.example.com/exec?action=unsubscribe' in html


def test_no_list_unsubscribe_without_token():
    msg = mailer.build_message(make_digest(), {"email": "a@example.com"}, "Konu")
    assert msg["List-Unsubscribe"] is None
