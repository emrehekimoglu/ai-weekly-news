"""E-posta gönderim sonuçlarının raporlanması (sahte SMTP ile, ağ yok)."""

import pytest

import main


class FakeSMTP:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, *args):
        pass

    def sendmail(self, sender, to, msg):
        if to.startswith("bad"):
            raise RuntimeError("550 rejected")


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    monkeypatch.setattr(main.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(main, "EMAIL_SENDER", "sender@example.com")


def test_all_sent_returns_empty_list():
    assert main.send_newsletter_to_all("<body></body>", [{"email": "ok@example.com"}]) == []


def test_failed_addresses_are_returned():
    recipients = [{"email": "ok@example.com"}, {"email": "bad@example.com"}]
    assert main.send_newsletter_to_all("<body></body>", recipients) == ["bad@example.com"]


def test_no_recipients_returns_none():
    assert main.send_newsletter_to_all("<body></body>", []) is None


@pytest.mark.parametrize("recipients,should_fail", [
    ([{"email": "ok@example.com"}], False),
    ([{"email": "ok@example.com"}, {"email": "bad@example.com"}], True),
    ([], True),
])
def test_main_exit_code(monkeypatch, recipients, should_fail):
    item = {"source": "s", "title": "t", "date": "d", "link": "l", "summary": "x"}
    for name in ["fetch_arxiv_papers", "fetch_hacker_news_ai", "fetch_github_trending_ai",
                 "fetch_company_blogs", "fetch_reddit_viral_ai", "fetch_tech_media_ai"]:
        monkeypatch.setattr(main, name, lambda: [item])
    monkeypatch.setattr(main, "DRY_RUN", False)
    monkeypatch.setattr(main, "check_config", lambda: [])
    monkeypatch.setattr(main, "generate_digest_with_opencode", lambda raw: "<body></body>")
    monkeypatch.setattr(main, "get_subscribers", lambda: recipients)

    if should_fail:
        with pytest.raises(SystemExit) as exc:
            main.main()
        assert exc.value.code == 1
    else:
        main.main()
