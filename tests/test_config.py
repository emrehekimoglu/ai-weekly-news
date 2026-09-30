"""Başlangıç ayar kontrolü, Sheets yedeği ve akış zaman aşımları (ağ ve sır gerektirmez)."""

import json

import pytest

import main

COMPLETE = {
    "OPENCODE_API_KEY": "key",
    "EMAIL_SENDER": "sender@example.com",
    "EMAIL_PASSWORD": "pw",
    "EMAIL_RECEIVER": "",
    "GCP_SA_KEY": json.dumps({"type": "service_account"}),
    "SPREADSHEET_ID": "sheet",
}


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # subscribers.txt yok
    for name, value in COMPLETE.items():
        monkeypatch.setattr(main, name, value)
    return lambda **kw: [monkeypatch.setattr(main, k, v) for k, v in kw.items()]


def test_complete_config_passes(config):
    assert main.check_config() == []


def test_missing_secrets_are_named(config):
    config(OPENCODE_API_KEY=None, EMAIL_PASSWORD="")
    problems = main.check_config()
    assert any("OPENCODE_API_KEY" in p for p in problems)
    assert any("EMAIL_PASSWORD" in p for p in problems)


def test_invalid_service_account_json(config):
    config(GCP_SA_KEY="{not json")
    assert any("JSON" in p for p in main.check_config())


def test_half_configured_sheets(config):
    config(SPREADSHEET_ID=None)
    assert any("birlikte" in p for p in main.check_config())


def test_email_receiver_alone_is_a_recipient_source(config):
    config(GCP_SA_KEY=None, SPREADSHEET_ID=None, EMAIL_RECEIVER="me@example.com")
    assert main.check_config() == []


def test_no_recipient_source(config):
    config(GCP_SA_KEY=None, SPREADSHEET_ID=None)
    assert any("Alıcı" in p for p in main.check_config())


def test_main_stops_before_fetching_when_config_missing(config, monkeypatch):
    config(OPENCODE_API_KEY=None)
    monkeypatch.setattr(main, "DRY_RUN", False)
    monkeypatch.setattr(main, "fetch_arxiv_papers", lambda: pytest.fail("veri toplanmamalıydı"))
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 1


def test_dry_run_skips_config_check(config, monkeypatch):
    config(OPENCODE_API_KEY=None)
    monkeypatch.setattr(main, "DRY_RUN", True)
    for name in ["fetch_arxiv_papers", "fetch_hacker_news_ai", "fetch_github_trending_ai",
                 "fetch_company_blogs", "fetch_reddit_viral_ai", "fetch_tech_media_ai"]:
        monkeypatch.setattr(main, name, lambda: [])
    main.main()  # SystemExit yok


def test_sheets_failure_falls_back_loudly(config, monkeypatch, capsys):
    config(EMAIL_RECEIVER="me@example.com", SHEETS_ERROR=None)
    monkeypatch.setattr(main, "HAS_GSPREAD", True)
    monkeypatch.setattr(main, "Credentials", None)  # from_service_account_info -> AttributeError
    assert main.get_subscribers() == [{"email": "me@example.com", "token": ""}]
    assert main.SHEETS_ERROR
    assert "::error::" in capsys.readouterr().out


def test_sheets_failure_fails_the_run_after_sending(config, monkeypatch):
    monkeypatch.setattr(main, "DRY_RUN", False)
    for name in ["fetch_arxiv_papers", "fetch_hacker_news_ai", "fetch_github_trending_ai",
                 "fetch_company_blogs", "fetch_reddit_viral_ai", "fetch_tech_media_ai"]:
        monkeypatch.setattr(main, name, lambda: [{"source": "s", "title": "t", "date": "d", "link": "l",
                                                  "summary": "x"}])
    monkeypatch.setattr(main, "generate_digest_with_opencode", lambda raw: "<body></body>")
    sent = []

    def fake_get_subscribers():
        main.SHEETS_ERROR = "Google Sheets okunamadı"
        return [{"email": "me@example.com", "token": ""}]

    monkeypatch.setattr(main, "SHEETS_ERROR", None)
    monkeypatch.setattr(main, "get_subscribers", fake_get_subscribers)
    monkeypatch.setattr(main, "send_newsletter_to_all", lambda html, r: sent.extend(r) or [])
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 1
    assert sent == [{"email": "me@example.com", "token": ""}]


class FakeResponse:
    content = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    def raise_for_status(self):
        pass


@pytest.mark.parametrize("fetch", [main.fetch_arxiv_papers, main.fetch_tech_media_ai])
def test_feeds_are_fetched_with_timeout(monkeypatch, fetch):
    timeouts = []
    monkeypatch.setattr(main.requests, "get", lambda url, headers=None, timeout=None: timeouts.append(timeout)
                        or FakeResponse())
    assert fetch() == []
    assert timeouts and all(t == main.FEED_TIMEOUT_SECONDS for t in timeouts)


def test_arxiv_timeout_does_not_crash(monkeypatch):
    def boom(*a, **kw):
        raise main.requests.Timeout("yavaş")

    monkeypatch.setattr(main.requests, "get", boom)
    assert main.fetch_arxiv_papers() == []
