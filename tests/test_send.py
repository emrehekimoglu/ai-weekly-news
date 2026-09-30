"""E-posta gönderim sonuçlarının raporlanması (sahte SMTP ile, ağ yok)."""

import pytest

from newsletter import app, config, llm, mailer, subscribers
from tests.conftest import make_digest, make_item


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
def fake_smtp(monkeypatch, set_config):
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(mailer.time, "sleep", lambda s: None)
    set_config(EMAIL_SENDER="sender@example.com")


def test_all_sent_returns_empty_list():
    assert mailer.send_all(make_digest(), [{"email": "ok@example.com"}]) == []


def test_failed_addresses_are_returned():
    recipients = [{"email": "ok@example.com"}, {"email": "bad@example.com"}]
    assert mailer.send_all(make_digest(), recipients) == ["bad@example.com"]


def test_no_recipients_returns_none():
    assert mailer.send_all(make_digest(), []) is None


@pytest.mark.parametrize("recipients,should_fail", [
    ([{"email": "ok@example.com"}], False),
    ([{"email": "ok@example.com"}, {"email": "bad@example.com"}], True),
    ([], True),
])
def test_main_exit_code(monkeypatch, set_config, fake_sources, recipients, should_fail):
    fake_sources([make_item()])
    set_config(DRY_RUN=False, PREVIEW=False)
    monkeypatch.setattr(config, "check_config", lambda: [])
    monkeypatch.setattr(llm, "generate_digest", lambda items: make_digest())
    monkeypatch.setattr(subscribers, "get_subscribers", lambda: (recipients, None))

    if should_fail:
        with pytest.raises(SystemExit) as exc:
            app.main()
        assert exc.value.code == 1
    else:
        app.main()
