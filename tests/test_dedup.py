"""Kaynaklar arası tekrarların ve önceki sayılarda çıkan haberlerin elenmesi (ağ yok)."""

import json

import pytest

from newsletter import app, config, history, llm, mailer, subscribers
from newsletter.dedup import normalize_link, normalize_title, remove_duplicates
from newsletter.llm import build_prompt
from tests.conftest import make_digest, make_item


@pytest.mark.parametrize("a,b", [
    ("https://www.theverge.com/ai/123/story/", "http://theverge.com/ai/123/story?utm_source=rss#comments"),
    ("https://www.reddit.com/r/LocalLLaMA/comments/abc/x/", "https://reddit.com/r/LocalLLaMA/comments/abc/x"),
    ("https://example.com/a?id=1&ref=hn", "https://EXAMPLE.com/a?id=1"),
    ("https://old.reddit.com/r/singularity/comments/abc/", "https://www.reddit.com/r/singularity/comments/abc"),
])
def test_same_links_normalize_equal(a, b):
    assert normalize_link(a) == normalize_link(b)


def test_different_query_ids_stay_different():
    assert normalize_link("https://news.ycombinator.com/item?id=1") != normalize_link(
        "https://news.ycombinator.com/item?id=2")


def test_title_normalization():
    assert normalize_title("  OpenAI Releases GPT-6! ") == normalize_title("openai releases gpt 6")


def test_remove_duplicates_keeps_first_by_link_or_title():
    items = [
        make_item(source="The Verge AI", title="GPT-6 çıktı", link="https://www.theverge.com/x"),
        make_item(source="Hacker News", title="OpenAI launches GPT-6", link="https://theverge.com/x/?utm_source=hn"),
        make_item(source="Ars Technica", title="GPT-6 Çıktı!", link="https://arstechnica.com/y"),
        make_item(source="arXiv", title="Başka bir makale", link="https://arxiv.org/abs/1"),
    ]
    assert [i.source for i in remove_duplicates(items)] == ["The Verge AI", "arXiv"]


def test_history_round_trip_keeps_last_issues(set_config, isolated_history):
    set_config(HISTORY_ISSUES=2)
    for date in ["2026-09-14", "2026-09-21", "2026-09-28"]:
        history.record(make_digest(1), date)
    history.record(make_digest(2), "2026-09-28")  # aynı gün tekrar çalışırsa üzerine yazar
    issues = history.load()
    assert [i["date"] for i in issues] == ["2026-09-21", "2026-09-28"]
    assert issues[-1]["entries"][1] == {"title": "Haber 2", "link": "https://example.com/2", "source": "s",
                                         "category": "Yeni Model"}
    assert history.recent_titles(issues, weeks=1) == ["Haber 1", "Haber 2"]


def test_missing_or_broken_history_is_empty(isolated_history):
    assert history.load() == []
    isolated_history.write_text("{bozuk", encoding="utf-8")
    assert history.load() == []


def test_remove_seen_drops_links_sent_before():
    issues = [{"date": "2026-09-21", "entries": [{"title": "Eski", "link": "https://www.example.com/1/"}]}]
    items = [make_item(link="https://example.com/1"), make_item(link="https://example.com/2")]
    assert [i.link for i in history.remove_seen(items, issues)] == ["https://example.com/2"]


def test_prompt_lists_previous_titles_only_when_present():
    assert "son sayılarda" not in build_prompt([make_item()])
    prompt = build_prompt([make_item()], ["GPT-6 çıktı"])
    assert "son sayılarda zaten işlendi" in prompt
    assert "- GPT-6 çıktı" in prompt


@pytest.fixture
def run(set_config, fake_sources, monkeypatch):
    set_config(DRY_RUN=False, PREVIEW=False)
    monkeypatch.setattr(config, "check_config", lambda: [])
    calls = {}

    def fake_generate(items, previous=(), reader_hint=""):
        calls["items"], calls["previous"] = items, previous
        return make_digest()

    monkeypatch.setattr(llm, "generate_digest", fake_generate)
    return calls


def test_main_filters_repeats_and_records_sent_issue(run, fake_sources, monkeypatch, isolated_history):
    isolated_history.write_text(json.dumps({"issues": [
        {"date": "2026-09-21", "entries": [{"title": "Geçen haftanın haberi", "link": "https://old.test/1"}]},
    ]}), encoding="utf-8")
    fake_sources([make_item(title="Eski", link="https://old.test/1"), make_item(title="Yeni", link="https://new.test/1"),
                  make_item(title="yeni!", link="https://other.test/1")])
    monkeypatch.setattr(subscribers, "get_subscribers", lambda: ([{"email": "a@example.com"}], None))
    monkeypatch.setattr(mailer, "send_all", lambda digest, r, subject=None: [])

    app.main()

    assert [i.title for i in run["items"]] == ["Yeni"]
    assert run["previous"] == ["Geçen haftanın haberi"]
    issues = history.load()
    assert len(issues) == 2 and issues[-1]["entries"][0]["title"] == "Haber 1"


def test_nothing_recorded_when_no_email_went_out(run, fake_sources, monkeypatch):
    fake_sources([make_item()])
    monkeypatch.setattr(subscribers, "get_subscribers", lambda: ([{"email": "bad@example.com"}], None))
    monkeypatch.setattr(mailer, "send_all", lambda digest, r, subject=None: ["bad@example.com"])
    with pytest.raises(SystemExit):
        app.main()
    assert history.load() == []


def test_preview_does_not_record(run, set_config, fake_sources, monkeypatch, tmp_path):
    set_config(PREVIEW=True, PREVIEW_EMAIL="me@example.com", PREVIEW_FILE=str(tmp_path / "n.html"))
    fake_sources([make_item()])
    monkeypatch.setattr(mailer, "send_all", lambda digest, r, subject=None: [])
    app.main()
    assert history.load() == []


def test_run_fails_when_everything_was_already_sent(run, fake_sources, isolated_history):
    isolated_history.write_text(json.dumps({"issues": [
        {"date": "2026-09-21", "entries": [{"title": "t", "link": "https://example.com/1"}]}]}), encoding="utf-8")
    fake_sources([make_item(link="https://example.com/1")])
    with pytest.raises(SystemExit) as exc:
        app.main()
    assert exc.value.code == 1
    assert "items" not in run
