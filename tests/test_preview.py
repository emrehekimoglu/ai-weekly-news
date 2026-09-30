"""Önizleme modu: bülten sadece sahibine gider, abone listesine hiç bakılmaz (ağ yok)."""

import pytest

from newsletter import app, config, llm, mailer, subscribers
from tests.conftest import make_item


@pytest.fixture
def preview_run(set_config, fake_sources, monkeypatch, tmp_path):
    fake_sources([make_item()])
    set_config(DRY_RUN=False, PREVIEW=True, PREVIEW_FILE=str(tmp_path / "newsletter.html"))
    monkeypatch.setattr(config, "check_config", lambda: [])
    monkeypatch.setattr(llm, "generate_digest", lambda items: "<body>bülten</body>")
    monkeypatch.setattr(subscribers, "get_subscribers", lambda: pytest.fail("önizlemede abone listesi okunmamalı"))

    sent = []
    monkeypatch.setattr(mailer, "send_all",
                        lambda html, recipients, subject=None: sent.append((recipients, subject)) or [])
    return sent


def test_preview_recipient_prefers_preview_email(set_config):
    set_config(PREVIEW_EMAIL="me@example.com", EMAIL_RECEIVER="other@example.com")
    assert subscribers.get_preview_recipients() == [{"email": "me@example.com", "token": ""}]


def test_preview_recipient_falls_back_to_receiver(set_config):
    set_config(PREVIEW_EMAIL=None, EMAIL_RECEIVER="owner@example.com")
    assert subscribers.get_preview_recipients() == [{"email": "owner@example.com", "token": ""}]


def test_preview_recipient_empty_without_address(set_config):
    set_config(PREVIEW_EMAIL="", EMAIL_RECEIVER=None)
    assert subscribers.get_preview_recipients() == []


def test_preview_sends_only_to_owner_and_saves_html(set_config, preview_run):
    set_config(PREVIEW_EMAIL="me@example.com")
    app.main()
    [(recipients, subject)] = preview_run
    assert recipients == [{"email": "me@example.com", "token": ""}]
    assert subject == f"[ÖNİZLEME] {mailer.newsletter_subject()}"
    with open(config.PREVIEW_FILE, encoding="utf-8") as f:
        assert f.read() == "<body>bülten</body>"


def test_preview_without_owner_address_fails(set_config, fake_sources, monkeypatch, tmp_path):
    fake_sources([make_item()])
    set_config(DRY_RUN=False, PREVIEW=True, PREVIEW_EMAIL=None, EMAIL_RECEIVER=None,
               PREVIEW_FILE=str(tmp_path / "newsletter.html"))
    monkeypatch.setattr(llm, "generate_digest", lambda items: "<body></body>")
    monkeypatch.setattr(subscribers, "get_subscribers", lambda: pytest.fail("abone listesi okundu"))
    with pytest.raises(SystemExit):
        app.main()
