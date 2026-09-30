"""E-posta biçimi: tarihli konu, düz metin sürümü ve iptal başlığı (ağ yok)."""

from datetime import datetime, timezone
from email import message_from_string

import pytest

import main

HTML = (
    "<html><head><style>p{color:red}</style></head><body>"
    "<h1>AI &amp; TEKNOLOJİ RADARI</h1><p>Haftanın özeti.</p>"
    '<p>Yeni model <a href="https://example.com/a?x=1">Kaynağa Git →</a></p>'
    "</body></html>"
)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(main, "EMAIL_SENDER", "sender@example.com")
    monkeypatch.setattr(main, "WEB_APP_URL", "https://script.example.com/exec")


def test_subject_contains_turkish_date():
    subject = main.newsletter_subject(datetime(2026, 9, 28, tzinfo=timezone.utc))
    assert subject.endswith("• 28 Eylül 2026")


def test_html_to_text_keeps_text_and_links():
    text = main.html_to_text(HTML)
    assert "color:red" not in text
    assert "AI & TEKNOLOJİ RADARI" in text
    assert "Haftanın özeti." in text
    assert "Kaynağa Git → (https://example.com/a?x=1)" in text
    assert "<" not in text


def test_unsubscribe_url_needs_web_app_and_token(monkeypatch):
    assert main.unsubscribe_url("a+b@example.com", "") is None
    assert main.unsubscribe_url("a+b@example.com", "t") == (
        "https://script.example.com/exec?action=unsubscribe&email=a%2Bb%40example.com&token=t"
    )
    monkeypatch.setattr(main, "WEB_APP_URL", "")
    assert main.unsubscribe_url("a@example.com", "t") is None


def test_message_has_plain_html_and_list_unsubscribe():
    msg = main.build_message(HTML, {"email": "a@example.com", "token": "t"}, "Konu")
    parsed = message_from_string(msg.as_string())
    assert parsed["List-Unsubscribe"] == (
        "<https://script.example.com/exec?action=unsubscribe&email=a%40example.com&token=t>"
    )
    parts = parsed.get_payload()
    assert [p.get_content_type() for p in parts] == ["text/plain", "text/html"]
    plain = parts[0].get_payload(decode=True).decode("utf-8")
    html = parts[1].get_payload(decode=True).decode("utf-8")
    assert "Haftanın özeti." in plain
    assert "(https://script.example.com/exec?action=unsubscribe" in plain
    assert 'href="https://script.example.com/exec?action=unsubscribe' in html


def test_no_list_unsubscribe_without_token():
    msg = main.build_message(HTML, {"email": "a@example.com"}, "Konu")
    assert msg["List-Unsubscribe"] is None


def test_prompt_does_not_hotlink_logo():
    import inspect
    assert "flaticon" not in inspect.getsource(main)
