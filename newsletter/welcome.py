"""Yeni okura onay anında gönderilen "son sayı" kopyası (data/latest-issue.json).

Gerçek gönderimden sonra sayı, okura özel bağlantıların yerinde yer tutucularla kaydedilir; iş akışı
dosyayı depoya commit eder. Cloudflare Worker, biri aboneliğini onayladığında dosyayı GitHub'dan okur,
yer tutucuları o okurun iptal ve oy bağlantılarıyla değiştirip e-postayı gönderir. Dosyada hiçbir
abone bilgisi yoktur (depo herkese açık).
"""

import json
import os
from urllib.parse import urlencode

from newsletter import config
from newsletter.render import render_html, render_text

# Worker'daki (worker/src/index.js) adlarla aynı olmalı
BASE = "__RADAR_BASE__"                # Worker'ın adresi, sonunda "/" ile
UNSUBSCRIBE = "__RADAR_UNSUBSCRIBE__"  # okurun iptal bağlantısı
VOTER = "__RADAR_VOTER__"              # mailer.feedback_url_builder ile aynı kısa okur kimliği


def _vote_url(issue):
    def build(story, vote):
        return f"{BASE}?{urlencode({'action': 'vote', 'issue': issue, 'story': story, 'v': vote, 'voter': VOTER})}"
    return build


def save(digest, issue, subject, path=None):
    """Hoş geldin e-postası için sayıyı yer tutucu bağlantılarla kaydeder."""
    path = path or config.WELCOME_FILE
    votes = _vote_url(issue)
    data = {
        "issue": issue,
        "subject": subject,
        "html": render_html(digest, UNSUBSCRIBE, votes, welcome=True),
        "text": render_text(digest, UNSUBSCRIBE, votes, welcome=True),
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
