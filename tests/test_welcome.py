"""Yeni okura onayda gönderilen son sayı kopyası (data/latest-issue.json): yer tutucular, abone verisi yok."""

import json

import pytest

from newsletter import app, config, llm, mailer, subscribers, welcome
from newsletter.render import render_html, render_text
from tests.conftest import make_digest, make_item


@pytest.fixture
def run(set_config, fake_sources, monkeypatch, tmp_path):
    fake_sources([make_item()])
    set_config(DRY_RUN=False, PREVIEW=False, PREVIEW_FILE=str(tmp_path / "newsletter.html"),
               ARCHIVE_FILE=str(tmp_path / "issue.html"))
    monkeypatch.setattr(config, "check_config", lambda: [])
    monkeypatch.setattr(llm, "generate_digest", lambda items, *args, **kwargs: make_digest(cover=True))
    monkeypatch.setattr(subscribers, "get_subscribers", lambda: ([{"email": "a@example.com", "token": "t"}], None))
    monkeypatch.setattr(subscribers, "get_preview_recipients", lambda: [{"email": "me@example.com", "token": ""}])
    monkeypatch.setattr(mailer, "send_all", lambda digest, recipients, subject=None: [])


def test_real_send_saves_welcome_copy_with_placeholders(run, isolated_welcome):
    app.main()
    saved = json.loads(isolated_welcome.read_text(encoding="utf-8"))
    assert saved["issue"] == mailer.issue_id()
    assert saved["subject"] == mailer.newsletter_subject(digest=make_digest(cover=True))
    vote = f"{welcome.BASE}?action=vote&issue={saved['issue']}&story=0&v=up&voter={welcome.VOTER}"
    for body in (saved["html"], saved["text"]):
        assert "Hoş geldiniz" in body
        assert welcome.UNSUBSCRIBE in body
        assert vote in body.replace("&amp;", "&")
        assert "a@example.com" not in body and "token=" not in body


@pytest.mark.parametrize("option", ["PREVIEW", "DRY_RUN"])
def test_preview_and_dry_run_do_not_save_welcome_copy(set_config, run, isolated_welcome, option):
    set_config(**{option: True})
    app.main()
    assert not isolated_welcome.exists()


def test_failed_send_does_not_save_welcome_copy(monkeypatch, run, isolated_welcome):
    monkeypatch.setattr(mailer, "send_all", lambda digest, recipients, subject=None: ["a@example.com"])
    with pytest.raises(SystemExit):
        app.main()
    assert not isolated_welcome.exists()


def test_regular_issue_has_no_welcome_box():
    assert "Hoş geldiniz" not in render_html(make_digest())
    assert "Hoş geldiniz" not in render_text(make_digest())
