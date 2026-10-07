"""Arşiv: RSS beslemesi, abone olma kutusu ve eski sayfaların yenilenmesi (ağ yok)."""

import xml.etree.ElementTree as ET

import pytest

import archive
from newsletter.render import render_html
from tests.conftest import make_digest

SITE = "https://emre.github.io/ai-weekly-news/"
ABONE = "https://radar.example.workers.dev/abone"
OLD_FORM = "https://forms.gle/Mtm8QNREUKR8CLZ19"


@pytest.fixture
def site(tmp_path):
    digest = make_digest(cover=True)
    digest.headline = "Sol & Argon: <yarış> kızıştı"
    issue = tmp_path / "issue.html"
    issue.write_text(render_html(digest), encoding="utf-8")

    def publish(*dates):
        for d in dates:
            archive.publish(str(issue), str(tmp_path / "site"), d)
        return tmp_path / "site"
    return publish


def test_feed_lists_issues_newest_first_with_headline_and_summary(set_config, site):
    set_config(ARCHIVE_URL=SITE)
    root = site("2026-09-28", "2026-10-05")
    channel = ET.parse(root / "feed.xml").getroot().find("channel")
    items = channel.findall("item")
    assert [i.findtext("link") for i in items] == [f"{SITE}issues/2026-10-05.html", f"{SITE}issues/2026-09-28.html"]
    assert items[0].findtext("title") == "Sol & Argon: <yarış> kızıştı (5 Ekim 2026)"
    assert items[0].findtext("description") == "Birinci madde."
    assert items[0].findtext("pubDate") == "Mon, 05 Oct 2026 06:00:00 +0000"
    index = (root / "index.html").read_text(encoding="utf-8")
    assert f'type="application/rss+xml" title="AI &amp; Teknoloji Radarı Arşivi" href="{SITE}feed.xml"' in index
    assert "Sol &amp; Argon: &lt;yarış&gt; kızıştı" in index


def test_feed_keeps_only_latest_issues(set_config, site, monkeypatch):
    set_config(ARCHIVE_URL=SITE)
    monkeypatch.setattr(archive, "FEED_ITEMS", 2)
    root = site("2026-09-14", "2026-09-21", "2026-09-28")
    links = [i.findtext("link") for i in ET.parse(root / "feed.xml").getroot().iter("item")]
    assert links == [f"{SITE}issues/2026-09-28.html", f"{SITE}issues/2026-09-21.html"]


def test_no_feed_without_archive_url(site):
    root = site("2026-09-28")
    assert not (root / "feed.xml").exists()
    assert "rss" not in (root / "index.html").read_text(encoding="utf-8").lower()


def test_signup_box_posts_to_worker_signup_page(set_config, site):
    set_config(SIGNUP_URL=ABONE, ARCHIVE_URL=SITE)
    root = site("2026-09-28")
    for page in (root / "index.html", root / "issues" / "2026-09-28.html"):
        content = page.read_text(encoding="utf-8")
        assert f'<form method="post" action="{ABONE}">' in content
        assert 'name="email"' in content and 'name="website"' in content
        assert f'href="{SITE}feed.xml"' in content


def test_signup_box_is_a_link_for_google_form(set_config, site):
    set_config(SIGNUP_URL=OLD_FORM)
    index = (site("2026-09-28") / "index.html").read_text(encoding="utf-8")
    assert "<form" not in index and f'href="{OLD_FORM}"' in index


def test_rebuild_points_old_pages_at_new_signup_page(set_config, site):
    set_config(SIGNUP_URL=OLD_FORM, ARCHIVE_URL=SITE)
    root = site("2026-09-28")
    page = root / "issues" / "2026-09-28.html"
    assert OLD_FORM in page.read_text(encoding="utf-8")

    set_config(SIGNUP_URL=ABONE)
    archive.rebuild(str(root))
    assert "forms.gle" not in page.read_text(encoding="utf-8")
    assert f'href="{ABONE}"' in page.read_text(encoding="utf-8")
    assert f'action="{ABONE}"' in (root / "index.html").read_text(encoding="utf-8")


def test_rebuild_cli(set_config, site, monkeypatch, capsys):
    set_config(ARCHIVE_URL=SITE)
    root = site("2026-09-28")
    (root / "feed.xml").unlink()
    monkeypatch.setattr("sys.argv", ["archive.py", "--rebuild", str(root)])
    with pytest.raises(SystemExit) as done:
        exec(compile(open(archive.__file__, encoding="utf-8").read(), archive.__file__, "exec"),
             {"__name__": "__main__", "__file__": archive.__file__})
    assert done.value.code == 0 and (root / "feed.xml").exists()
