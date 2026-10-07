"""Çalışma raporu: kaynak sayıları, uyarılar ve okur oyları özeti, iş akışının uyarı e-postası (alert.py) için dosyaya yazılır.

Her değişiklikte dosya yeniden yazılır; çalışma ortasında çökse bile o ana kadarki bilgi kalır.
"""

import json
import logging

from newsletter import config

log = logging.getLogger(__name__)

_report = {"sources": {}, "warnings": [], "votes": []}


def reset():
    _report["sources"] = {}
    _report["warnings"] = []
    _report["votes"] = []


def set_sources(counts):
    """{kaynak adı: haber sayısı}; boş dönen kaynaklar için uyarı eklenir."""
    _report["sources"] = dict(counts)
    for name, count in counts.items():
        if count == 0:
            warn(f"{name} kaynağı boş döndü (0 haber)")
    _save()


def warn(message):
    """GitHub Actions'ta sarı uyarı olarak görünür ve uyarı e-postasına girer."""
    log.warning("::warning::%s", message)
    _report["warnings"].append(message)
    _save()


def set_votes(lines):
    """Okur oyları özeti (votes.summary_lines); gerçek gönderimde sahibe giden e-postaya girer."""
    _report["votes"] = list(lines)
    _save()


def add_warning(message):
    """Başka bir süreçten (ör. Telegram adımı) dosyadaki rapora uyarı ekler; uyarı e-postası bunu da gösterir."""
    log.warning("::warning::%s", message)
    data = load()
    data["warnings"].append(message)
    try:
        with open(config.REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log.warning("Çalışma raporu yazılamadı: %s", e)


def _save():
    try:
        with open(config.REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(_report, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log.warning("Çalışma raporu yazılamadı: %s", e)


def load(path=None):
    try:
        with open(path or config.REPORT_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"sources": {}, "warnings": [], "votes": []}
    return {"sources": data.get("sources") or {}, "warnings": data.get("warnings") or [],
            "votes": data.get("votes") or []}
