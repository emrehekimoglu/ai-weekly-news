"""Yedek zamanlama: sadece otomatik gönderimler sayılır, elle gönderilenler değil (ağ yok)."""

import contextlib
import json
from datetime import date

import pytest

from newsletter import app, config, history
from tests.conftest import make_digest

MONDAY = date(2026, 10, 12)


def test_only_scheduled_sends_in_last_6_days_count():
    assert history.scheduled_send_within([{"date": "2026-10-12", "scheduled": True}], 6, today=MONDAY)
    assert history.scheduled_send_within([{"date": "2026-10-07", "scheduled": True}], 6, today=MONDAY)
    assert not history.scheduled_send_within([{"date": "2026-10-05", "scheduled": True}], 6, today=MONDAY)
    # Pazar günü elle gönderilen sayı pazartesi sayısını engellemez
    assert not history.scheduled_send_within([{"date": "2026-10-11"}], 6, today=MONDAY)
    assert not history.scheduled_send_within([], 6, today=MONDAY)


def test_record_marks_scheduled_and_keeps_mark_on_same_day_manual_resend(isolated_history):
    history.record(make_digest(1), "2026-10-12", scheduled=True)
    history.record(make_digest(2), "2026-10-12")
    history.record(make_digest(1), "2026-10-11")
    issues = json.loads(isolated_history.read_text(encoding="utf-8"))["issues"]
    assert [(i["date"], i.get("scheduled")) for i in issues] == [("2026-10-12", True), ("2026-10-11", None)]


@pytest.fixture
def collected(monkeypatch, set_config):
    """Veri toplama başladı mı? (başladıysa çalışma atlanmamıştır)"""
    calls = []
    set_config(SCHEDULED=True, DRY_RUN=False, PREVIEW=False)
    monkeypatch.setattr(config, "check_config", lambda: [])
    monkeypatch.setattr(app, "collect", lambda sources: calls.append(1) or {})
    return calls


def test_backup_run_skips_when_scheduled_run_already_sent(monkeypatch, collected):
    monkeypatch.setattr(history, "scheduled_send_within", lambda issues, days: True)
    app.main()
    assert collected == []


def test_scheduled_run_proceeds_when_no_scheduled_send_this_week(monkeypatch, collected):
    monkeypatch.setattr(history, "scheduled_send_within", lambda issues, days: False)
    with contextlib.suppress(SystemExit):  # sahte toplama boş döner; gerçek gönderimde bu hata sayılır
        app.main()
    assert collected == [1]


@pytest.mark.parametrize("override", [{"SCHEDULED": False}, {"PREVIEW": True}, {"DRY_RUN": True}])
def test_manual_preview_and_dry_runs_never_skip(monkeypatch, set_config, collected, override):
    set_config(**override)
    monkeypatch.setattr(history, "scheduled_send_within", lambda issues, days: True)
    with contextlib.suppress(SystemExit):
        app.main()
    assert collected == [1]
