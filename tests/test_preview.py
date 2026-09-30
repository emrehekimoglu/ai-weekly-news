"""Önizleme modu: bülten sadece sahibine gider, abone listesine hiç bakılmaz (ağ yok)."""

import pytest

import main


@pytest.fixture
def preview_run(monkeypatch, tmp_path):
    item = {"source": "s", "title": "t", "date": "d", "link": "l", "summary": "x"}
    for name in ["fetch_arxiv_papers", "fetch_hacker_news_ai", "fetch_github_trending_ai",
                 "fetch_company_blogs", "fetch_reddit_viral_ai", "fetch_tech_media_ai"]:
        monkeypatch.setattr(main, name, lambda: [item])
    monkeypatch.setattr(main, "DRY_RUN", False)
    monkeypatch.setattr(main, "PREVIEW", True)
    monkeypatch.setattr(main, "check_config", lambda: [])
    monkeypatch.setattr(main, "generate_digest_with_opencode", lambda raw: "<body>bülten</body>")
    monkeypatch.setattr(main, "PREVIEW_FILE", str(tmp_path / "newsletter.html"))

    def no_subscribers():
        raise AssertionError("önizlemede abone listesi okunmamalı")
    monkeypatch.setattr(main, "get_subscribers", no_subscribers)

    sent = []
    monkeypatch.setattr(main, "send_newsletter_to_all",
                        lambda html, recipients, subject="": sent.append((recipients, subject)) or [])
    return sent


def test_preview_recipient_prefers_preview_email(monkeypatch):
    monkeypatch.setattr(main, "PREVIEW_EMAIL", "me@example.com")
    monkeypatch.setattr(main, "EMAIL_RECEIVER", "other@example.com")
    assert main.get_preview_recipients() == [{"email": "me@example.com", "token": ""}]


def test_preview_recipient_falls_back_to_receiver(monkeypatch):
    monkeypatch.setattr(main, "PREVIEW_EMAIL", None)
    monkeypatch.setattr(main, "EMAIL_RECEIVER", "owner@example.com")
    assert main.get_preview_recipients() == [{"email": "owner@example.com", "token": ""}]


def test_preview_recipient_empty_without_address(monkeypatch):
    monkeypatch.setattr(main, "PREVIEW_EMAIL", "")
    monkeypatch.setattr(main, "EMAIL_RECEIVER", None)
    assert main.get_preview_recipients() == []


def test_preview_sends_only_to_owner_and_saves_html(monkeypatch, preview_run):
    monkeypatch.setattr(main, "PREVIEW_EMAIL", "me@example.com")
    main.main()
    [(recipients, subject)] = preview_run
    assert recipients == [{"email": "me@example.com", "token": ""}]
    assert subject == f"[ÖNİZLEME] {main.newsletter_subject()}"
    with open(main.PREVIEW_FILE, encoding="utf-8") as f:
        assert f.read() == "<body>bülten</body>"


def test_preview_without_owner_address_fails(monkeypatch, tmp_path):
    item = {"source": "s", "title": "t", "date": "d", "link": "l", "summary": "x"}
    for name in ["fetch_arxiv_papers", "fetch_hacker_news_ai", "fetch_github_trending_ai",
                 "fetch_company_blogs", "fetch_reddit_viral_ai", "fetch_tech_media_ai"]:
        monkeypatch.setattr(main, name, lambda: [item])
    monkeypatch.setattr(main, "DRY_RUN", False)
    monkeypatch.setattr(main, "PREVIEW", True)
    monkeypatch.setattr(main, "PREVIEW_EMAIL", None)
    monkeypatch.setattr(main, "EMAIL_RECEIVER", None)
    monkeypatch.setattr(main, "PREVIEW_FILE", str(tmp_path / "newsletter.html"))
    monkeypatch.setattr(main, "generate_digest_with_opencode", lambda raw: "<body></body>")
    monkeypatch.setattr(main, "get_subscribers", lambda: pytest.fail("abone listesi okundu"))
    with pytest.raises(SystemExit):
        main.main()
