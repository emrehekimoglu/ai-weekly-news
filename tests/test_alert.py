"""Güvenilir pazartesiler: kaynak sağlık kontrolü, yedek model ve uyarı e-postası (ağ yok)."""

import email
import email.header
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from newsletter import alert, app, config, llm, report
from newsletter.sources import Source, collect
from tests.conftest import make_item

MONDAY = datetime(2026, 10, 12, 3, 5, tzinfo=timezone.utc)


# --- Kaynak sağlık kontrolü ---

def test_collect_logs_count_per_source(caplog):
    with caplog.at_level("INFO"):
        collect([Source("A", "a", lambda: [make_item()]), Source("B", "b", lambda: [])])
    assert "Kaynak özeti: A 1, B 0" in caplog.text


def test_empty_source_is_reported(monkeypatch, set_config, isolated_report):
    monkeypatch.setattr(app, "SOURCES", [Source("Dolu", "d", lambda: [make_item()]), Source("GitHub", "g", lambda: [])])
    set_config(DRY_RUN=True)
    app.main()
    data = json.loads(isolated_report.read_text(encoding="utf-8"))
    assert data["sources"] == {"Dolu": 1, "GitHub": 0}
    assert data["warnings"] == ["GitHub kaynağı boş döndü (0 haber)"]


def test_no_items_at_all_fails_the_run(monkeypatch, set_config, fake_sources):
    fake_sources([])
    set_config(DRY_RUN=False, PREVIEW=False, SCHEDULED=False)
    monkeypatch.setattr(config, "check_config", lambda: [])
    with pytest.raises(SystemExit) as exc:
        app.main()
    assert exc.value.code == 1


# --- Yedek model ---

class FakeClient:
    """Verilen modeller için geçerli yanıt, diğerleri için hata döndürür."""

    def __init__(self, working_models):
        self.working = working_models
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, model, **kwargs):
        self.calls.append(model)
        if model not in self.working:
            raise RuntimeError("502 Bad Gateway")
        picks = [{"id": i, "title": f"H{i}", "category": "Yeni Model", "summary": "Özet."} for i in range(1, 6)]
        content = json.dumps({"intro": "Giriş.", "items": picks})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def llm_setup(monkeypatch, set_config):
    set_config(MODEL_NAME="ana", FALLBACK_MODEL_NAME="yedek", LLM_MAX_ATTEMPTS=3)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    def use(working):
        client = FakeClient(working)
        monkeypatch.setattr(llm, "_client", lambda: client)
        return client
    return use


ITEMS = [make_item(link=f"https://example.com/{i}") for i in range(1, 6)]


def test_main_model_is_used_when_it_works(llm_setup):
    client = llm_setup({"ana", "yedek"})
    llm.generate_digest(ITEMS)
    assert client.calls == ["ana"]
    assert report.load()["warnings"] == []


def test_fallback_model_after_three_failures(llm_setup):
    client = llm_setup({"yedek"})
    digest = llm.generate_digest(ITEMS)
    assert len(digest.entries) == 5
    assert client.calls == ["ana", "ana", "ana", "yedek"]
    assert "yedek modelle (yedek)" in report.load()["warnings"][0]


def test_both_models_failing_raises(llm_setup):
    client = llm_setup(set())
    with pytest.raises(RuntimeError, match="ana.*yedek"):
        llm.generate_digest(ITEMS)
    assert client.calls == ["ana"] * 3 + ["yedek"] * 3


def test_no_fallback_when_same_or_empty(llm_setup, set_config):
    for fallback in ("", "ana"):
        set_config(FALLBACK_MODEL_NAME=fallback)
        client = llm_setup(set())
        with pytest.raises(RuntimeError):
            llm.generate_digest(ITEMS)
        assert client.calls == ["ana"] * 3


# --- Uyarı e-postası ---

def test_nothing_to_report_on_clean_success():
    assert alert.build_alert("success", {"sources": {"A": 3}, "warnings": []}, ["log"]) is None


def test_failure_alert_has_run_link_and_log_tail():
    subject, body = alert.build_alert("failure", {"sources": {"A": 3, "B": 0}, "warnings": ["B kaynağı boş döndü"]},
                                      ["[HATA] Gönderilecek abone bulunamadı!"], "https://github.com/x/y/actions/runs/1",
                                      today=MONDAY)
    assert subject == "⚠️ Bülten çalışması başarısız • 12 Ekim 2026"
    assert "https://github.com/x/y/actions/runs/1" in body
    assert "- B kaynağı boş döndü" in body
    assert "- B: 0" in body
    assert "abone bulunamadı" in body
    assert "yedek çalışma" not in body


def test_main_cron_failure_mentions_backup_run():
    _, body = alert.build_alert("failure", {}, [], schedule="0 3 * * 1")
    assert "04:37 UTC" in body


def test_warnings_alone_send_a_softer_alert():
    subject, body = alert.build_alert("success", {"sources": {}, "warnings": ["GitHub kaynağı boş döndü"]},
                                      ["gizli log"], today=MONDAY)
    assert subject.startswith("⚠️ Bülten gönderildi, 1 uyarı var")
    assert "GitHub kaynağı boş döndü" in body
    assert "gizli log" not in body


def test_log_tail_strips_actions_markers(tmp_path):
    path = tmp_path / "run.log"
    path.write_text("\n".join(f"satır {i}" for i in range(100)) + "\n::error::kötü\n", encoding="utf-8")
    tail = alert.log_tail(str(path))
    assert len(tail) == alert.LOG_TAIL_LINES
    assert tail[-1] == "kötü"
    assert alert.log_tail(str(tmp_path / "yok.log")) == []


def test_recipient_order(monkeypatch, set_config):
    set_config(ALERT_EMAIL="", EMAIL_SENDER="ben@gmail.com")
    monkeypatch.delenv("PREVIEW_EMAIL", raising=False)
    assert alert.recipient() == "ben@gmail.com"
    monkeypatch.setenv("PREVIEW_EMAIL", "onizleme@example.com")
    assert alert.recipient() == "onizleme@example.com"
    set_config(ALERT_EMAIL="uyari@example.com")
    assert alert.recipient() == "uyari@example.com"


class FakeSMTP:
    sent = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, *a):
        pass

    def sendmail(self, sender, to, msg):
        FakeSMTP.sent.append((sender, to, msg))


@pytest.fixture
def smtp(monkeypatch, set_config):
    FakeSMTP.sent = []
    monkeypatch.setattr(alert.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("GITHUB_REPOSITORY", "emre/ai-weekly-news")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.delenv("PREVIEW_EMAIL", raising=False)
    set_config(EMAIL_SENDER="ben@gmail.com", EMAIL_PASSWORD="x", ALERT_EMAIL="")
    return FakeSMTP.sent


def test_main_sends_on_failure(smtp, tmp_path):
    assert alert.main(["--status", "failure", "--log", str(tmp_path / "run.log")]) == 0
    assert len(smtp) == 1
    sender, to, raw = smtp[0]
    assert to == "ben@gmail.com"
    body = email.message_from_string(raw).get_payload(decode=True).decode("utf-8")
    assert "https://github.com/emre/ai-weekly-news/actions/runs/42" in body


def test_main_quiet_on_clean_success(smtp, tmp_path):
    report.set_sources({"A": 2})
    assert alert.main(["--status", "success", "--log", str(tmp_path / "run.log")]) == 0
    assert smtp == []


def test_main_reports_missing_credentials(smtp, set_config, tmp_path):
    set_config(EMAIL_PASSWORD=None)
    assert alert.main(["--status", "failure", "--log", str(tmp_path / "run.log")]) == 1
    assert smtp == []


def test_config_defaults_have_a_distinct_fallback():
    assert config.FALLBACK_MODEL_NAME and config.FALLBACK_MODEL_NAME != config.MODEL_NAME


def test_test_flag_sends_a_marked_sample(smtp):
    assert alert.main(["--test"]) == 0
    msg = email.message_from_string(smtp[0][2])
    assert "[DENEME]" in str(email.header.make_header(email.header.decode_header(msg["Subject"])))
    assert "gerçek bir sorun yok" in msg.get_payload(decode=True).decode("utf-8")


def test_fallback_test_breaks_main_model_and_forces_preview(monkeypatch):
    import importlib
    monkeypatch.setenv("FALLBACK_TEST", "true")
    try:
        importlib.reload(config)
        assert config.PREVIEW is True
        assert config.MODEL_NAME == "olmayan-model-yedek-testi"
        assert config.FALLBACK_MODEL_NAME and config.FALLBACK_MODEL_NAME != config.MODEL_NAME
    finally:
        monkeypatch.delenv("FALLBACK_TEST")
        importlib.reload(config)
    assert not config.FALLBACK_TEST


def test_fallback_test_preview_subject_is_marked(monkeypatch, set_config, fake_sources):
    from newsletter import mailer, subscribers
    from tests.conftest import make_digest
    fake_sources([make_item()])
    set_config(DRY_RUN=False, PREVIEW=True, FALLBACK_TEST=True, SCHEDULED=False, PREVIEW_FILE="/dev/null")
    monkeypatch.setattr(config, "check_config", lambda: [])
    monkeypatch.setattr(llm, "generate_digest", lambda items, *args: make_digest())
    monkeypatch.setattr(subscribers, "get_preview_recipients", lambda: [{"email": "ben@example.com"}])
    subjects = []
    monkeypatch.setattr(mailer, "send_all", lambda digest, recipients, subject=None: subjects.append(subject) or [])
    app.main()
    assert subjects[0].startswith("[YEDEK MODEL TESTİ] [ÖNİZLEME] ")


def test_llm_waits_long_enough_for_slow_models(llm_setup):
    client = llm_setup({"ana"})
    timeouts = []
    original = client.create
    client.chat.completions.create = lambda model, **kw: timeouts.append(kw["timeout"]) or original(model, **kw)
    llm.generate_digest(ITEMS)
    assert timeouts == [config.LLM_TIMEOUT_SECONDS]
    assert config.LLM_TIMEOUT_SECONDS >= 400  # qwen3.8-max ~335 sn sürüyor


def test_openai_client_has_no_hidden_retries(set_config):
    set_config(OPENCODE_API_KEY="x")
    assert llm._client().max_retries == 0
