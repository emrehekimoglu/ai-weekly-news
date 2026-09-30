"""Başlangıç ayar kontrolü, Sheets yedeği ve akış zaman aşımları (ağ ve sır gerektirmez)."""

import json
import logging

import pytest
import requests

from newsletter import app, config, llm, mailer, subscribers
from newsletter.sources import Source, arxiv, collect, media
from tests.conftest import make_item

COMPLETE = {
    "OPENCODE_API_KEY": "key",
    "EMAIL_SENDER": "sender@example.com",
    "EMAIL_PASSWORD": "pw",
    "EMAIL_RECEIVER": "",
    "GCP_SA_KEY": json.dumps({"type": "service_account"}),
    "SPREADSHEET_ID": "sheet",
    "PREVIEW": False,
    "PREVIEW_EMAIL": None,
    "DRY_RUN": False,
}


@pytest.fixture
def cfg(set_config, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # subscribers.txt yok
    set_config(**COMPLETE)
    return set_config


def test_complete_config_passes(cfg):
    assert config.check_config() == []


def test_missing_secrets_are_named(cfg):
    cfg(OPENCODE_API_KEY=None, EMAIL_PASSWORD="")
    problems = config.check_config()
    assert any("OPENCODE_API_KEY" in p for p in problems)
    assert any("EMAIL_PASSWORD" in p for p in problems)


def test_invalid_service_account_json(cfg):
    cfg(GCP_SA_KEY="{not json")
    assert any("JSON" in p for p in config.check_config())


def test_half_configured_sheets(cfg):
    cfg(SPREADSHEET_ID=None)
    assert any("birlikte" in p for p in config.check_config())


def test_email_receiver_alone_is_a_recipient_source(cfg):
    cfg(GCP_SA_KEY=None, SPREADSHEET_ID=None, EMAIL_RECEIVER="me@example.com")
    assert config.check_config() == []


def test_no_recipient_source(cfg):
    cfg(GCP_SA_KEY=None, SPREADSHEET_ID=None)
    assert any("Alıcı" in p for p in config.check_config())


def test_preview_needs_owner_address_not_sheet(cfg):
    cfg(PREVIEW=True, GCP_SA_KEY=None, SPREADSHEET_ID=None)
    assert any("Önizleme" in p for p in config.check_config())
    cfg(PREVIEW_EMAIL="me@example.com")
    assert config.check_config() == []


def test_main_stops_before_fetching_when_config_missing(cfg, fake_sources):
    cfg(OPENCODE_API_KEY=None)
    fake_sources(fetch=lambda: pytest.fail("veri toplanmamalıydı"))
    with pytest.raises(SystemExit) as exc:
        app.main()
    assert exc.value.code == 1


def test_dry_run_skips_config_check(cfg, fake_sources):
    cfg(OPENCODE_API_KEY=None, DRY_RUN=True)
    fake_sources([])
    app.main()  # SystemExit yok


def test_dry_run_lists_items_per_source(cfg, fake_sources, caplog):
    cfg(DRY_RUN=True)
    fake_sources([make_item(title="Yeni model")])
    with caplog.at_level(logging.INFO):
        app.main()
    assert "Sahte: 1" in caplog.text
    assert "Yeni model" in caplog.text


def test_sheets_failure_falls_back_loudly(cfg, monkeypatch, caplog):
    cfg(EMAIL_RECEIVER="me@example.com")
    monkeypatch.setattr(subscribers, "HAS_GSPREAD", True)
    monkeypatch.setattr(subscribers, "Credentials", None)  # from_service_account_info -> AttributeError
    recipients, error = subscribers.get_subscribers()
    assert recipients == [{"email": "me@example.com", "token": ""}]
    assert error
    assert "::error::" in caplog.text


def test_sheets_failure_fails_the_run_after_sending(cfg, fake_sources, monkeypatch):
    fake_sources([make_item()])
    monkeypatch.setattr(llm, "generate_digest", lambda items: "<body></body>")
    recipients = [{"email": "me@example.com", "token": ""}]
    monkeypatch.setattr(subscribers, "get_subscribers", lambda: (recipients, "Google Sheets okunamadı"))
    sent = []
    monkeypatch.setattr(mailer, "send_all", lambda html, r, subject=None: sent.extend(r) or [])
    with pytest.raises(SystemExit) as exc:
        app.main()
    assert exc.value.code == 1
    assert sent == recipients


class FakeResponse:
    content = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    def raise_for_status(self):
        pass


@pytest.mark.parametrize("fetch", [arxiv.fetch, media.fetch])
def test_feeds_are_fetched_with_timeout(monkeypatch, fetch):
    timeouts = []
    monkeypatch.setattr(requests, "get", lambda url, headers=None, timeout=None: timeouts.append(timeout)
                        or FakeResponse())
    assert fetch() == []
    assert timeouts and all(t == config.FEED_TIMEOUT_SECONDS for t in timeouts)


def test_failing_source_is_skipped(monkeypatch):
    def boom(*a, **kw):
        raise requests.Timeout("yavaş")

    monkeypatch.setattr(requests, "get", boom)
    item = make_item()
    results = collect([Source("arXiv", "arXiv", arxiv.fetch), Source("Diğer", "diğer", lambda: [item])])
    assert results == {"arXiv": [], "Diğer": [item]}
