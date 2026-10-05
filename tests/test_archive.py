"""Web arşivi: abone verisi yayınlanmaz, sadece gerçek gönderimler arşive girer (ağ yok)."""

import pytest

import archive
from newsletter import app, config, llm, mailer, subscribers
from newsletter.render import render_html
from tests.conftest import make_digest, make_item

ISSUE = render_html(make_digest())


def test_sanitize_removes_personal_footer_from_sent_email(set_config):
    set_config(WEB_APP_URL="https://script.google.com/macros/s/abc/exec", EMAIL_SENDER="sender@example.com")
    msg = mailer.build_message(make_digest(), {"email": "okur@example.com", "token": "gizli-token"}, "konu")
    sent_html = msg.get_payload()[1].get_payload(decode=True).decode("utf-8")
    assert "gizli-token" in sent_html

    cleaned = archive.sanitize(sent_html)
    assert "gizli-token" not in cleaned
    assert "okur@example.com" not in cleaned
    assert "abone olduğunuz" not in cleaned
    assert "action=vote" not in cleaned
    assert "https://example.com/5" in cleaned


def test_archive_issue_has_no_feedback_links():
    assert "action=vote" not in ISSUE and "Bu sayı nasıldı?" not in ISSUE


def test_sanitize_drops_token_and_mailto_links_but_keeps_sources():
    content = ('<body><a href="https://x.dev/p?id=1">ok</a>'
               '<a href="https://app/exec?action=unsubscribe&amp;email=a%40b.com">çık</a>'
               '<a href="https://app/?token=abc">t</a><a href="mailto:a@b.com">m</a></body>')
    cleaned = archive.sanitize(content)
    assert 'href="https://x.dev/p?id=1"' in cleaned
    for leaked in ("unsubscribe", "token=", "a@b.com", "a%40b.com"):
        assert leaked not in cleaned


def test_sanitize_strips_scripts_and_event_handlers():
    content = ('<body onload="alert(1)"><script>alert(2)</script><img src=x onerror=alert(3)>'
               '<a href="javascript:alert(4)">x</a></body>')
    cleaned = archive.sanitize(content).lower()
    assert "alert" not in cleaned


def test_publish_writes_issue_and_newest_first_index(tmp_path):
    issue = tmp_path / "issue.html"
    issue.write_text(ISSUE, encoding="utf-8")
    site = tmp_path / "site"
    archive.publish(str(issue), str(site), "2026-09-21")
    archive.publish(str(issue), str(site), "2026-09-28")

    page = (site / "issues" / "2026-09-28.html").read_text(encoding="utf-8")
    assert page.startswith("<!DOCTYPE html>")
    assert "28 Eylül 2026" in page and "../index.html" in page
    assert '<meta name="viewport"' in page

    index = (site / "index.html").read_text(encoding="utf-8")
    assert index.index("2026-09-28.html") < index.index("2026-09-21.html")
    assert "2 sayı" in index
    assert (site / ".nojekyll").exists()


def test_publish_rejects_bad_date(tmp_path):
    issue = tmp_path / "issue.html"
    issue.write_text(ISSUE, encoding="utf-8")
    with pytest.raises(ValueError):
        archive.publish(str(issue), str(tmp_path / "site"), "../../etc")


@pytest.fixture
def run(set_config, fake_sources, monkeypatch, tmp_path):
    fake_sources([make_item()])
    set_config(DRY_RUN=False, PREVIEW=False, PREVIEW_FILE=str(tmp_path / "newsletter.html"),
               ARCHIVE_FILE=str(tmp_path / "issue.html"))
    monkeypatch.setattr(config, "check_config", lambda: [])
    monkeypatch.setattr(llm, "generate_digest", lambda items, *args, **kwargs: make_digest())
    monkeypatch.setattr(subscribers, "get_subscribers", lambda: ([{"email": "a@example.com", "token": "t"}], None))
    monkeypatch.setattr(subscribers, "get_preview_recipients", lambda: [{"email": "me@example.com", "token": ""}])
    monkeypatch.setattr(mailer, "send_all", lambda digest, recipients, subject=None: [])
    return tmp_path / "issue.html"


def test_real_send_saves_shared_issue_for_archive(run):
    app.main()
    saved = run.read_text(encoding="utf-8")
    assert saved == render_html(make_digest())
    assert "token" not in saved and "a@example.com" not in saved


def test_preview_does_not_save_issue_for_archive(set_config, run):
    set_config(PREVIEW=True)
    app.main()
    assert not run.exists()


def test_dry_run_does_not_save_issue_for_archive(set_config, run):
    set_config(DRY_RUN=True)
    app.main()
    assert not run.exists()


def test_no_recipients_does_not_save_issue_for_archive(monkeypatch, run):
    monkeypatch.setattr(mailer, "send_all", lambda digest, recipients, subject=None: None)
    with pytest.raises(SystemExit):
        app.main()
    assert not run.exists()
