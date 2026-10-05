"""Yedek zamanlama: bu hafta zaten gönderildiyse zamanlanmış çalışma tekrar göndermez (ağ yok)."""

from datetime import date

import pytest

from newsletter import app, config, history


def test_sent_within_counts_today_and_last_days_only():
    issues = [{"date": "2026-09-28"}]
    assert history.sent_within(issues, 6, today=date(2026, 9, 28))
    assert history.sent_within(issues, 6, today=date(2026, 10, 3))
    assert not history.sent_within(issues, 6, today=date(2026, 10, 5))
    assert not history.sent_within([], 6, today=date(2026, 10, 5))


@pytest.fixture
def collected(monkeypatch, set_config):
    """Veri toplama başladı mı? (başladıysa çalışma atlanmamıştır)"""
    calls = []
    set_config(SCHEDULED=True, DRY_RUN=False, PREVIEW=False)
    monkeypatch.setattr(config, "check_config", lambda: [])
    monkeypatch.setattr(app, "collect", lambda sources: calls.append(1) or {})
    return calls


def test_scheduled_run_skips_when_issue_already_sent_this_week(monkeypatch, collected):
    monkeypatch.setattr(history, "sent_within", lambda issues, days: True)
    app.main()
    assert collected == []


def test_scheduled_run_proceeds_when_nothing_sent_this_week(monkeypatch, collected):
    monkeypatch.setattr(history, "sent_within", lambda issues, days: False)
    app.main()
    assert collected == [1]


@pytest.mark.parametrize("override", [{"SCHEDULED": False}, {"PREVIEW": True}, {"DRY_RUN": True}])
def test_manual_preview_and_dry_runs_never_skip(monkeypatch, set_config, collected, override):
    set_config(**override)
    monkeypatch.setattr(history, "sent_within", lambda issues, days: True)
    app.main()
    assert collected == [1]
