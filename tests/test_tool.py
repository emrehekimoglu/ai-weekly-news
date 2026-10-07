""""Haftanın Aracı" bölümü: model seçimi, doğrulama, şablonlar ve geçmiş (ağ yok)."""

import json

import pytest

from newsletter import history
from newsletter.llm import build_prompt, parse_digest
from newsletter.models import Tool
from newsletter.render import render_html, render_text
from tests.conftest import make_digest, make_item

SOURCES = ["arXiv"] * 6 + ["GitHub Açık Kaynak", "Hacker News", "Reddit r/LocalLLaMA", "GitHub Açık Kaynak"]
ITEMS = [make_item(title=f"Ham {i}", link=f"https://example.com/{i}", source=s) for i, s in enumerate(SOURCES, 1)]
GOOD = {"id": 7, "name": "Notlarım AI", "what": "Notlarınızı özetler.", "how": "Siteye girip notunuzu yapıştırın."}


def answer(arac):
    picks = [{"id": i, "title": f"Haber {i}", "category": "Araştırma", "summary": f"Özet {i}."} for i in range(1, 6)]
    return json.dumps({"intro": "Giriş.", "items": picks, "arac": arac}, ensure_ascii=False)


def test_prompt_asks_for_tool():
    prompt = build_prompt(ITEMS)
    assert '"arac": {"id": 12,' in prompt and "Haftanın Aracı" in prompt


@pytest.mark.parametrize("arac", [GOOD, {**GOOD, "id": "8"}])
def test_parse_reads_tool_from_github_or_hn(arac):
    tool = parse_digest(answer(arac), ITEMS).tool
    assert tool.name == "Notlarım AI" and tool.item.link == f"https://example.com/{int(arac['id'])}"


@pytest.mark.parametrize("arac", [
    None, "yok", [], {**GOOD, "id": 1}, {**GOOD, "id": 9}, {**GOOD, "id": 99}, {**GOOD, "how": ""},
    {**GOOD, "name": "x" * 200}, {k: v for k, v in GOOD.items() if k != "what"},
])
def test_missing_or_bad_tool_skips_section_without_failing(arac):
    digest = parse_digest(answer(arac), ITEMS)
    assert digest.tool is None and len(digest.entries) == 5
    assert "HAFTANIN ARACI" not in render_html(digest) and "HAFTANIN ARACI" not in render_text(digest)


def test_tool_rendered_in_html_and_text():
    digest = make_digest()
    digest.tool = Tool(item=make_item(link="https://github.com/a/b"), name="Notlarım AI",
                       what="Notlarınızı özetler.", how="Siteye girip notunuzu yapıştırın.")
    page, text = render_html(digest), render_text(digest)
    for out in (page, text):
        assert "HAFTANIN ARACI" in out and "Notlarım AI" in out and "Siteye girip notunuzu yapıştırın." in out
        assert "https://github.com/a/b" in out


def test_history_records_tool_link_so_it_is_not_repeated():
    digest = make_digest(2)
    digest.tool = Tool(item=make_item(link="https://github.com/a/b"), name="Araç", what="x", how="y")
    history.record(digest, "2026-10-12")
    assert history.normalize_link("https://github.com/a/b") in history.seen_links(history.load())
