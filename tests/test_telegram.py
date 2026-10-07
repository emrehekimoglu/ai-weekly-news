"""Telegram kanalı gönderisi (ağ yok: Telegram ve GitHub Pages istekleri sahte)."""

import json
from types import SimpleNamespace

import pytest

from newsletter import app, config, history, report, telegram
from tests.conftest import make_digest

SUMMARY = {
    "date": "2026-10-12",
    "headline": "Açık kaynak arayı <kapattı> mı?",
    "intro": "Haftanın özeti.",
    "tldr": ["Birinci madde.", "İkinci & madde."],
    "titles": ["Haber 1", "Haber 2"],
}


@pytest.fixture
def post_file(isolated_post_file):
    isolated_post_file.write_text(json.dumps(SUMMARY), encoding="utf-8")
    return isolated_post_file


@pytest.fixture
def bot(monkeypatch, set_config):
    """Sahte Telegram: gönderilen istekleri kaydeder; `reply` ile yanıt değiştirilebilir."""
    set_config(TELEGRAM_BOT_TOKEN="123:SECRET", TELEGRAM_CHAT_ID="@kanal",
               ARCHIVE_URL="https://emre.github.io/ai-weekly-news/", SIGNUP_URL="https://radar.example/abone")
    state = SimpleNamespace(calls=[], reply={"ok": True}, page_status=200)

    def post(url, json=None, timeout=None):
        state.calls.append((url, json))
        return SimpleNamespace(status_code=200, json=lambda: state.reply)

    monkeypatch.setattr(telegram.requests, "post", post)
    monkeypatch.setattr(telegram.requests, "get", lambda url, timeout=None: SimpleNamespace(status_code=state.page_status))
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(telegram.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(telegram.time, "sleep", lambda s: setattr(clock, "now", clock.now + s))
    return state


def record_issue(date="2026-10-12"):
    history.record(make_digest(), date)


def test_message_has_headline_points_and_links():
    text = telegram.build_message(SUMMARY, "https://x.io/issues/2026-10-12.html", "https://radar.example/abone")
    assert "12 Ekim 2026" in text
    assert "<b>Açık kaynak arayı &lt;kapattı&gt; mı?</b>" in text
    assert "• İkinci &amp; madde." in text
    assert "Haber 1" not in text  # tldr varken başlıklar tekrar edilmez
    assert '<a href="https://x.io/issues/2026-10-12.html">' in text
    assert "abone" in text


def test_message_falls_back_to_titles_and_stays_short():
    summary = {**SUMMARY, "headline": None, "tldr": [], "titles": [f"Başlık {i} " + "x" * 1000 for i in range(9)]}
    text = telegram.build_message(summary)
    assert sum(line.startswith("• ") for line in text.splitlines()) == telegram.MAX_POINTS
    assert len(text) < 4096
    assert "<a " not in text


def test_skipped_without_secrets(set_config, post_file, monkeypatch):
    set_config(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    monkeypatch.setattr(telegram.requests, "post", lambda *a, **k: pytest.fail("istek atılmamalı"))
    assert telegram.post_issue() == "skipped"
    assert telegram.main([]) == 0


def test_skipped_when_no_issue_was_sent(bot, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "POST_FILE", str(tmp_path / "yok.json"))
    assert telegram.post_issue() == "skipped"
    assert bot.calls == []


def test_posts_once_and_marks_history(bot, post_file):
    record_issue()
    assert telegram.post_issue() == "posted"
    url, payload = bot.calls[0]
    assert url.endswith("/sendMessage")
    assert payload["chat_id"] == "@kanal"
    assert payload["parse_mode"] == "HTML"
    assert payload["link_preview_options"] == {"url": "https://emre.github.io/ai-weekly-news/issues/2026-10-12.html"}
    assert history.posted_to_telegram("2026-10-12")

    # Aynı gün elle tekrar gönderilen sayı kanala ikinci kez gitmez
    record_issue()
    assert telegram.post_issue() == "skipped"
    assert len(bot.calls) == 1


def test_waits_for_page_but_posts_anyway(bot, post_file):
    bot.page_status = 404
    record_issue()
    assert telegram.post_issue() == "posted"


def test_failure_is_a_warning_and_hides_token(bot, post_file, isolated_report):
    bot.reply = {"ok": False, "description": "Forbidden: bot 123:SECRET is not a member of the channel chat"}
    record_issue()
    assert telegram.main([]) == 0  # bülten çalışması kırmızı olmaz
    warnings = report.load()["warnings"]
    assert len(warnings) == 1
    assert "Telegram" in warnings[0] and "not a member" in warnings[0]
    assert "SECRET" not in warnings[0]
    assert not history.posted_to_telegram("2026-10-12")


def test_failure_keeps_earlier_warnings(bot, post_file, isolated_report):
    report.warn("GitHub kaynağı boş döndü (0 haber)")
    bot.reply = {"ok": False, "description": "Bad Request: chat not found"}
    telegram.post_issue()
    assert len(report.load()["warnings"]) == 2


def test_test_message(bot):
    assert telegram.main(["--test"]) == 0
    assert bot.calls[0][1]["link_preview_options"] == {"is_disabled": True}


def test_test_message_needs_secrets(set_config):
    set_config(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    assert telegram.main(["--test"]) == 1


def test_post_summary_fields(isolated_post_file):
    app.write_post_summary(make_digest(cover=True), "2026-10-12")
    data = json.loads(isolated_post_file.read_text(encoding="utf-8"))
    assert data["date"] == "2026-10-12"
    assert data["headline"] == "Açık kaynak arayı kapattı mı?"
    assert len(data["tldr"]) == 3 and data["titles"][0] == "Haber 1"
