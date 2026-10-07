"""Paylaşım: e-postada abonelik/web bağlantıları ve arşiv sayfalarında paylaşım bağlantıları (ağ yok)."""

from datetime import datetime, timezone

import archive
from newsletter import config, mailer
from newsletter.render import render_html, render_text
from tests.conftest import make_digest

SIGNUP = "https://forms.gle/abone"
SITE = "https://emre.github.io/ai-weekly-news/"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_no_share_blocks_without_settings():
    html, text = render_html(make_digest()), render_text(make_digest())
    assert "arkadaşınıza iletin" not in html and "arkadaşınıza iletin" not in text
    assert "web'de okuyabilir" not in html and "Web'de okuyun" not in text


def test_email_has_forward_block_and_web_link(set_config):
    set_config(SIGNUP_URL=SIGNUP, ARCHIVE_URL=SITE)
    html, text = render_html(make_digest()), render_text(make_digest())
    page = f"{SITE}issues/{TODAY}.html"
    assert "arkadaşınıza iletin" in html and f'href="{SIGNUP}"' in html and f'href="{page}"' in html
    assert SIGNUP in text and page in text


def test_preview_has_no_web_link_because_it_is_never_archived(set_config):
    set_config(SIGNUP_URL=SIGNUP, ARCHIVE_URL=SITE, PREVIEW=True)
    html, text = render_html(make_digest()), render_text(make_digest())
    assert f"{SITE}issues/" not in html and f"{SITE}issues/" not in text
    assert f'href="{SIGNUP}"' in html


def test_archive_keeps_signup_but_drops_web_link_with_footer(set_config):
    set_config(SIGNUP_URL=SIGNUP, ARCHIVE_URL=SITE, WEB_APP_URL="https://script.example.com/exec",
               EMAIL_SENDER="sender@example.com")
    msg = mailer.build_message(make_digest(), {"email": "okur@example.com", "token": "gizli"}, "konu")
    cleaned = archive.sanitize(msg.get_payload()[1].get_payload(decode=True).decode("utf-8"))
    assert f'href="{SIGNUP}"' in cleaned
    assert "web'de okuyabilir" not in cleaned and "gizli" not in cleaned


def test_issue_page_has_share_links_without_subscriber_data(set_config, tmp_path):
    set_config(SIGNUP_URL=SIGNUP, ARCHIVE_URL=SITE)
    issue = tmp_path / "issue.html"
    issue.write_text(render_html(make_digest(), "https://x/exec?action=unsubscribe&email=a%40b.com&token=t"),
                     encoding="utf-8")
    page = open(archive.publish(str(issue), str(tmp_path / "site"), "2026-09-28"), encoding="utf-8").read()
    encoded = "https%3A%2F%2Femre.github.io%2Fai-weekly-news%2Fissues%2F2026-09-28.html"
    for target in ("twitter.com/intent/tweet", "linkedin.com/sharing", "wa.me/", "t.me/share"):
        assert target in page
    assert page.count(encoded) >= 4
    assert f'<meta property="og:url" content="{SITE}issues/2026-09-28.html">' in page
    assert "token=" not in page and "a%40b.com" not in page and "unsubscribe" not in page
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert f'href="{SIGNUP}"' in index


def test_issue_page_has_no_share_links_without_archive_url(tmp_path):
    issue = tmp_path / "issue.html"
    issue.write_text(render_html(make_digest()), encoding="utf-8")
    page = open(archive.publish(str(issue), str(tmp_path / "site"), "2026-09-28"), encoding="utf-8").read()
    assert "Paylaş:" not in page and "og:url" not in page and "abone olun" not in page


def test_archive_url_defaults_to_github_pages(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "EmreHekimoglu/ai-weekly-news")
    assert config._default_archive_url() == "https://emrehekimoglu.github.io/ai-weekly-news/"
    monkeypatch.delenv("GITHUB_REPOSITORY")
    assert config._default_archive_url() == ""
