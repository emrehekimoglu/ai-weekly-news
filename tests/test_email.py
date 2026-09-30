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


def test_subject_uses_headline_when_present():
    day = datetime(2026, 9, 28, tzinfo=timezone.utc)
    assert mailer.newsletter_subject(day, make_digest(cover=True)) == "Açık kaynak arayı kapattı mı? • Radar, 28 Eylül 2026"
    assert mailer.newsletter_subject(day, make_digest()) == mailer.newsletter_subject(day)


def test_html_template_has_cover_story_ranked_list_and_footer():
    html = render_html(make_digest(), UNSUB)
    assert "AI &amp; TEKNOLOJİ RADARI" in html
    assert "29 Eylül 2026" in html
    assert "Haftanın özeti." in html
    assert "Kapak Haberi · Yeni Model" in html
    assert html.count("Haberin tamamı &rarr;") == 1
    assert html.count("Devamı &rarr;") == 4
    for i in range(1, 6):
        assert f'href="https://example.com/{i}"' in html
    assert ">05<" in html and ">01<" not in html
    assert 'href="https://script.example.com/exec?action=unsubscribe&amp;email=a%40example.com&amp;token=t"' in html
    assert "<img" not in html and "<script" not in html


def test_html_template_skips_cover_blocks_without_cover_fields():
    html = render_html(make_digest())
    assert "30 SANİYEDE BU HAFTA" not in html
    assert "HAFTANIN RAKAMI" not in html
    assert ">Haftanın Özeti<" in html


def test_html_template_shows_cover_blocks():
    html = render_html(make_digest(cover=True))
    assert "Açık kaynak arayı kapattı mı?" in html
    assert "30 SANİYEDE BU HAFTA" in html and html.count("&rarr;&nbsp; ") == 3
    assert "HAFTANIN RAKAMI" in html and "10 GW" in html and "Rekor çip siparişi." in html


def test_html_template_escapes_model_text():
    digest = make_digest()
    digest.entries[0].summary = '<script>alert(1)</script> & "tırnak"'
    html = render_html(digest)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="#"' in html  # iptal bağlantısı yoksa


def test_text_template():
    text = render_text(make_digest(), UNSUB)
    assert text.startswith("AI & TEKNOLOJİ RADARI • 29 Eylül 2026\n")
    assert "1. Haber 1\nYeni Model • s • 28 Eylül 2026\nÖzet 1.\nKaynağa Git → https://example.com/1\n" in text
    assert "<" not in text
    assert f"Abonelikten ayrılmak için: {UNSUB}" in text
    assert "Abonelikten ayrılmak için" not in render_text(make_digest())


def test_text_template_with_cover_fields():
    text = render_text(make_digest(cover=True))
    assert "AÇIK KAYNAK ARAYI KAPATTI MI?\n\nHaftanın özeti.\n" in text
    assert "30 SANİYEDE BU HAFTA\n→ Birinci madde.\n→ İkinci madde.\n→ Üçüncü madde.\n" in text
    assert "HAFTANIN RAKAMI: 10 GW\nRekor çip siparişi.\n" in text


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
