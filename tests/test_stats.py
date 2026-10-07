"""Haftalık abone istatistikleri (sahte Sheets ile, ağ yok)."""

import json

import pytest
from gspread.exceptions import WorksheetNotFound

from newsletter import app, llm, mailer, stats, subscribers
from tests.conftest import make_digest, make_item

HEADER = ["Zaman", "E-posta", "Durum", "Token"]


class FakeWorksheet:
    def __init__(self, rows):
        self.rows = [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def append_row(self, row):
        self.rows.append(list(row))


class FakeSpreadsheet:
    def __init__(self, subscriber_rows, stats_rows=None):
        self.sheet1 = FakeWorksheet(subscriber_rows)
        self.tabs = {} if stats_rows is None else {stats.STATS_SHEET: FakeWorksheet(stats_rows)}

    def worksheet(self, title):
        if title not in self.tabs:
            raise WorksheetNotFound(title)
        return self.tabs[title]

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = FakeWorksheet([])
        return self.tabs[title]


@pytest.fixture
def sheet(monkeypatch, set_config):
    set_config(GCP_SA_KEY=json.dumps({"type": "service_account"}), SPREADSHEET_ID="sheet")

    def apply(subscriber_rows, stats_rows=None):
        spreadsheet = FakeSpreadsheet(subscriber_rows, stats_rows)
        monkeypatch.setattr(stats, "_open_spreadsheet", lambda: spreadsheet)
        return spreadsheet
    return apply


ROWS = [
    HEADER,
    ["1", "a@example.com", "AKTIF", "t1"],
    ["2", "b@example.com", "AKTIF", "t2"],
    ["3", "c@example.com", "AKTIF", "t3"],
    ["4", "B@example.com ", "IPTAL", "t2"],  # b ayrıldı (en yeni kaydı geçerli)
    ["5", "", "AKTIF", ""],                  # e-postasız satır sayılmaz
]


def test_count_uses_newest_row_per_email():
    assert stats.count(ROWS) == stats.Counts(active=2, total=3, inactive=1)


def test_unsubscribed_row_newer_than_signup_is_not_a_recipient():
    latest = subscribers.latest_rows(ROWS)
    emails = [email for email, (status, _) in latest.items() if status == "AKTIF"]
    assert sorted(emails) == ["a@example.com", "c@example.com"]


def test_first_row_has_no_changes():
    row = stats.build_row("2026-10-05", stats.Counts(2, 3, 1), None, sent=2, failed=0)
    assert row == ["2026-10-05", 2, "", "", "", 2, 0, 3, 1]


def test_changes_since_previous_send():
    previous = stats.Counts(active=10, total=12, inactive=2)
    now = stats.Counts(active=12, total=15, inactive=3)  # 3 yeni kayıt, 1 ayrılan
    row = stats.build_row("2026-10-12", now, previous, sent=12, failed=0)
    assert row[1:5] == [12, 3, 1, 2]


def test_resubscribe_is_not_negative_unsubscribes():
    previous = stats.Counts(active=10, total=12, inactive=2)
    now = stats.Counts(active=11, total=12, inactive=1)
    assert stats.build_row("d", now, previous, 11, 0)[2:5] == [0, 0, 1]


def test_previous_counts_skips_bad_rows():
    rows = [stats.HEADER, ["d1", "5", "", "", "", "5", "0", "6", "1"], ["d2", "x"]]
    assert stats.previous_counts(rows) == stats.Counts(active=5, total=6, inactive=1)
    assert stats.previous_counts([stats.HEADER]) is None


def test_record_creates_tab_and_appends(sheet):
    spreadsheet = sheet(ROWS)
    stats.record("2026-10-05", sent=2, failed=0)
    stats.record("2026-10-12", sent=2, failed=0)
    tab = spreadsheet.tabs[stats.STATS_SHEET].rows
    assert tab[0] == stats.HEADER
    assert tab[1] == ["2026-10-05", 2, "", "", "", 2, 0, 3, 1]
    assert tab[2] == ["2026-10-12", 2, 0, 0, 0, 2, 0, 3, 1]


def test_record_never_writes_or_logs_emails(sheet, caplog):
    spreadsheet = sheet(ROWS, stats_rows=[stats.HEADER])
    with caplog.at_level("INFO"):
        stats.record("2026-10-05", sent=2, failed=0)
    assert "@" not in json.dumps(spreadsheet.tabs[stats.STATS_SHEET].rows)
    assert "@" not in caplog.text
    assert "2 aktif abone" in caplog.text


def test_record_failure_only_warns(set_config, caplog):
    set_config(GCP_SA_KEY="{}", SPREADSHEET_ID="sheet")
    assert stats.record("d", 1, 0) is None
    assert "::warning::" in caplog.text


def test_record_skipped_without_sheet(set_config, monkeypatch):
    set_config(GCP_SA_KEY=None, SPREADSHEET_ID=None)
    monkeypatch.setattr(stats, "_open_spreadsheet", lambda: pytest.fail("Sheets açılmamalıydı"))
    assert stats.record("d", 1, 0) is None


@pytest.fixture
def run_main(monkeypatch, set_config, fake_sources, tmp_path):
    monkeypatch.chdir(tmp_path)
    set_config(OPENCODE_API_KEY="k", EMAIL_SENDER="s@example.com", EMAIL_PASSWORD="p",
               EMAIL_RECEIVER="", PREVIEW_EMAIL="me@example.com", DRY_RUN=False, PREVIEW=False,
               GCP_SA_KEY=json.dumps({"type": "service_account"}), SPREADSHEET_ID="sheet")
    fake_sources([make_item(link=f"https://example.com/{i}") for i in range(6)])
    monkeypatch.setattr(llm, "generate_digest", lambda items, *args: make_digest())
    monkeypatch.setattr(mailer, "send_all", lambda digest, recipients, subject=None: [])
    recorded = []
    monkeypatch.setattr(stats, "record", lambda *a, **kw: recorded.append((a, kw)))

    def apply(**values):
        set_config(**values)
        try:
            app.main()
        except SystemExit:
            pass
        return recorded
    return apply


def test_real_send_records_stats(run_main, monkeypatch):
    monkeypatch.setattr(subscribers, "get_subscribers",
                        lambda: ([{"email": "a@example.com", "token": ""}], None))
    recorded = run_main()
    assert len(recorded) == 1
    assert recorded[0][1] == {"sent": 1, "failed": 0}


def test_preview_and_dry_run_never_record(run_main, monkeypatch):
    monkeypatch.setattr(subscribers, "get_subscribers", lambda: pytest.fail("abone listesi okunmamalıydı"))
    assert run_main(PREVIEW=True) == []
    assert run_main(PREVIEW=False, DRY_RUN=True) == []


def test_sheets_fallback_does_not_record(run_main, monkeypatch):
    monkeypatch.setattr(subscribers, "get_subscribers",
                        lambda: ([{"email": "a@example.com", "token": ""}], "Google Sheets okunamadı"))
    assert run_main() == []
