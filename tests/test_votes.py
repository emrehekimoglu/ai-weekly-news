"""Okur oyları: haftalık özet ve modele hafif ipucu (ağ yok)."""

from newsletter import alert, app, config, llm, report, votes
from tests.conftest import make_item

HEADER = ["Zaman", "Sayı", "Haber", "Oy", "Okur"]
ISSUES = [
    {"date": "2026-09-30", "entries": [{"title": "Eski haber", "link": "l0", "source": "s"}]},  # kategorisiz eski kayıt
    {"date": "2026-10-05", "entries": [
        {"title": "GPT-7", "link": "l1", "source": "s", "category": "Yeni Model"},
        {"title": "Yeni makale", "link": "l2", "source": "s", "category": "Araştırma"},
        {"title": "Ankara girişimi", "link": "l3", "source": "s", "category": "Türkiye"},
    ]},
]


def row(issue, story, vote, voter="a"):
    return ["2026-10-06 08:00:00", issue, str(story), vote, voter]


def test_no_votes_means_no_hint_and_no_summary():
    t = votes.tally([HEADER], ISSUES)
    assert votes.reader_hint(t) == ""
    assert votes.summary_lines(t, "") == []
    assert votes.tally([], []).stories == []


def test_preview_unknown_and_broken_rows_are_ignored():
    rows = [HEADER,
            row("onizleme-2026-10-07", 1, "up"),   # mail-tester / önizleme
            row("2026-10-01", 1, "up"),            # geçmişte olmayan sayı
            row("2026-10-05", 9, "up"),            # olmayan haber
            row("2026-10-05", "x", "up"),
            row("2026-10-05", 1, "maybe"),
            ["kısa"],
            row("2026-10-05", 1, "up")]
    t = votes.tally(rows, ISSUES)
    assert [(s.title, s.up, s.down) for s in t.stories] == [("GPT-7", 1, 0)]


def test_tally_maps_stories_and_whole_issue_votes():
    rows = [HEADER, row("2026-10-05", 1, "up", "a"), row("2026-10-05", 1, "up", "b"),
            row("2026-10-05", 2, "down", "a"), row("2026-10-05", 0, "up", "a"), row("2026-09-30", 1, "up", "a")]
    t = votes.tally(rows, ISSUES)
    assert t.issue_votes == {"2026-10-05": [1, 0]}
    assert t.story_votes == 4
    assert t.categories() == {"Yeni Model": [2, 0], "Araştırma": [0, 1]}  # eski kayıt kategorisiz


def test_too_few_votes_give_no_hint():
    t = votes.tally([HEADER, row("2026-10-05", 1, "up"), row("2026-10-05", 2, "down")], ISSUES)
    assert votes.reader_hint(t) == ""
    lines = votes.summary_lines(t, "")
    assert "- 1. GPT-7: 👍 1 / 👎 0" in lines
    assert any("seçki oylardan etkilenmedi" in line for line in lines)


def test_enough_votes_give_gentle_hint():
    rows = [HEADER] + [row("2026-10-05", 1, "up", v) for v in "abc"] + [row("2026-10-05", 2, "down", v) for v in "ab"]
    t = votes.tally(rows, ISSUES)
    hint = votes.reader_hint(t)
    assert "daha çok beğendiği türler: Yeni Model" in hint
    assert "Daha az ilgi gören türler: Araştırma" in hint
    assert "Beğenilen haberlerden örnekler: GPT-7" in hint
    assert "AYNEN geçerli" in hint and "ASLA dışarıda bırakma" in hint
    assert any("hafifçe yönelmesi" in line for line in votes.summary_lines(t, hint))


def test_prompt_includes_hint_only_when_given():
    assert "OKUR GERİ BİLDİRİMİ" not in llm.build_prompt([make_item()])
    prompt = llm.build_prompt([make_item()], [], "\nOKUR GERİ BİLDİRİMİ: test\n")
    assert prompt.index("OKUR GERİ BİLDİRİMİ") < prompt.index("YAZIM KURALLARI")


def test_sheet_error_does_not_stop_the_run(set_config, caplog):
    set_config(GCP_SA_KEY="{}", SPREADSHEET_ID="x")
    assert votes.load_rows() == []  # conftest Sheets'i hata verecek şekilde değiştirir
    assert "Okur oyları okunamadı" in caplog.text


def test_no_sheet_config_reads_nothing(set_config, monkeypatch):
    set_config(GCP_SA_KEY=None, SPREADSHEET_ID=None)
    monkeypatch.setattr(votes, "_open_spreadsheet", lambda: (_ for _ in ()).throw(AssertionError))
    assert votes.collect(ISSUES) == ("", [])


def test_run_passes_hint_to_model_and_summary_to_report(monkeypatch, set_config, fake_sources, isolated_report):
    fake_sources([make_item()])
    set_config(DRY_RUN=False, PREVIEW=True)
    monkeypatch.setattr(config, "check_config", lambda: [])
    monkeypatch.setattr(votes, "collect", lambda issues: ("İPUCU", ["özet satırı"]))
    seen = {}

    def fake_generate(items, previous=(), reader_hint=""):
        seen["hint"] = reader_hint
        raise RuntimeError("model çağrılmadı")

    monkeypatch.setattr(llm, "generate_digest", fake_generate)
    try:
        app.main()
    except SystemExit:
        pass
    assert seen["hint"] == "İPUCU"
    assert report.load()["votes"] == ["özet satırı"]


def test_owner_gets_vote_summary_even_without_problems():
    subject, body = alert.build_alert("success", {"sources": {"arXiv": 3}, "warnings": [], "votes": ["- 1. GPT-7: 👍 2 / 👎 0"]},
                                      [], "https://run")
    assert subject.startswith("📊 Bülten gönderildi • okur oyları")
    assert "Okur oyları" in body and "GPT-7: 👍 2" in body
    assert alert.build_alert("success", {"sources": {}, "warnings": [], "votes": []}, []) is None


def test_vote_summary_rides_along_with_warnings():
    subject, body = alert.build_alert("success", {"warnings": ["GitHub boş"], "votes": ["- oy"]}, [])
    assert "uyarı var" in subject and "- oy" in body
