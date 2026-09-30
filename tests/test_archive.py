"""Web arşivi: abone verisi yayınlanmaz, sadece gerçek gönderimler arşive girer (ağ yok)."""

import pytest

import archive
import main

CARDS = "".join(f'<div><b>Haber {i}</b><a href="https://example.com/{i}">Kaynağa Git →</a></div>' for i in range(6))
ISSUE = f"<html><head><title>x</title></head><body>{CARDS}</body></html>"


def test_sanitize_removes_personal_footer_from_sent_email(monkeypatch):
    monkeypatch.setattr(main, "WEB_APP_URL", "https://script.google.com/macros/s/abc/exec")
    monkeypatch.setattr(main, "EMAIL_SENDER", "sender@example.com")
    msg = main.build_message(ISSUE, {"email": "okur@example.com", "token": "gizli-token"}, "konu")
    sent_html = msg.get_payload()[1].get_payload(decode=True).decode("utf-8")
    assert "gizli-token" in sent_html

    cleaned = archive.sanitize(sent_html)
    assert "gizli-token" not in cleaned
    assert "okur@example.com" not in cleaned
    assert "abone olduğunuz" not in cleaned
    assert "https://example.com/5" in cleaned


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
def run(monkeypatch, tmp_path):
    item = {"source": "s", "title": "t", "date": "d", "link": "l", "summary": "x"}
    for name in ["fetch_arxiv_papers", "fetch_hacker_news_ai", "fetch_github_trending_ai",
                 "fetch_company_blogs", "fetch_reddit_viral_ai", "fetch_tech_media_ai"]:
        monkeypatch.setattr(main, name, lambda: [item])
    monkeypatch.setattr(main, "DRY_RUN", False)
    monkeypatch.setattr(main, "PREVIEW", False)
    monkeypatch.setattr(main, "SHEETS_ERROR", None)
    monkeypatch.setattr(main, "check_config", lambda: [])
    monkeypatch.setattr(main, "generate_digest_with_opencode", lambda raw: ISSUE)
    monkeypatch.setattr(main, "get_subscribers", lambda: [{"email": "a@example.com", "token": "t"}])
    monkeypatch.setattr(main, "get_preview_recipients", lambda: [{"email": "me@example.com", "token": ""}])
    monkeypatch.setattr(main, "PREVIEW_FILE", str(tmp_path / "newsletter.html"))
    monkeypatch.setattr(main, "ARCHIVE_FILE", str(tmp_path / "issue.html"))
    monkeypatch.setattr(main, "send_newsletter_to_all", lambda html, recipients, subject=None: [])
    return tmp_path / "issue.html"


def test_real_send_saves_issue_for_archive(run):
    main.main()
    assert run.read_text(encoding="utf-8") == ISSUE


def test_preview_does_not_save_issue_for_archive(monkeypatch, run):
    monkeypatch.setattr(main, "PREVIEW", True)
    main.main()
    assert not run.exists()


def test_dry_run_does_not_save_issue_for_archive(monkeypatch, run):
    monkeypatch.setattr(main, "DRY_RUN", True)
    main.main()
    assert not run.exists()


def test_no_recipients_does_not_save_issue_for_archive(monkeypatch, run):
    monkeypatch.setattr(main, "send_newsletter_to_all", lambda html, recipients, subject=None: None)
    with pytest.raises(SystemExit):
        main.main()
    assert not run.exists()
