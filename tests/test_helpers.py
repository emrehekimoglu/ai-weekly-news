"""Ağ, LLM veya e-posta gerektirmeyen yardımcı fonksiyon testleri."""

import json
import time

import pytest

from newsletter import config
from newsletter.dates import parse_to_turkish_date
from newsletter.llm import MAX_DIGEST_CARDS, build_prompt, extract_json, parse_digest
from tests.conftest import make_item

ITEMS = [make_item(title=f"Ham {i}", link=f"https://example.com/{i}", date=f"{i} Eylül 2026") for i in range(1, 16)]


def answer(count=config.MIN_DIGEST_CARDS, **overrides):
    picks = [{"id": i, "title": f"Haber {i}", "category": "Araştırma", "summary": f"Özet {i}."}
             for i in range(1, count + 1)]
    return json.dumps({"intro": "Bu hafta çok şey oldu.", "items": picks, **overrides}, ensure_ascii=False)


# --- parse_to_turkish_date ---

def test_parse_iso_string():
    assert parse_to_turkish_date("2026-09-28T10:00:00Z") == "28 Eylül 2026"


def test_parse_struct_time():
    st = time.strptime("2026-01-05", "%Y-%m-%d")
    assert parse_to_turkish_date(st) == "5 Ocak 2026"


@pytest.mark.parametrize("value", [None, "", "dün", "2026-13-45"])
def test_parse_invalid_falls_back(value):
    assert parse_to_turkish_date(value) == "Bu Hafta"


# --- build_prompt ---

def test_prompt_lists_numbered_items_and_asks_for_json():
    prompt = build_prompt(ITEMS[:2])
    assert "[1] Kaynak: s\nBaşlık: Ham 1\n" in prompt
    assert "[2] Kaynak: s\nBaşlık: Ham 2\nYayın Tarihi: 2 Eylül 2026\nLink: https://example.com/2\nÖzet: x\n" in prompt
    assert '{"intro": "...", "items": [{"id": 3,' in prompt
    assert "Güvenlik & Olay" in prompt


# --- extract_json ---

@pytest.mark.parametrize("raw", ['```json\n{"a": 1}\n```', 'İşte bülten: {"a": 1} umarım beğenirsin', '  {"a": 1}  '])
def test_extract_json(raw):
    assert extract_json(raw) == {"a": 1}


@pytest.mark.parametrize("raw", ["<html></html>", '{"a": 1', ""])
def test_extract_json_rejects_non_json(raw):
    with pytest.raises(ValueError):
        extract_json(raw)


# --- parse_digest ---

def test_parse_takes_link_and_date_from_source_item():
    digest = parse_digest(answer(), ITEMS)
    assert digest.intro == "Bu hafta çok şey oldu."
    first = digest.entries[0]
    assert (first.title, first.category, first.summary) == ("Haber 1", "Araştırma", "Özet 1.")
    assert first.item.link == "https://example.com/1"
    assert first.item.date == "1 Eylül 2026"


def test_parse_accepts_numeric_string_ids_and_skips_repeats():
    data = json.loads(answer(6))
    data["items"][0]["id"] = "1"
    data["items"][1]["id"] = 1
    digest = parse_digest(json.dumps(data), ITEMS)
    assert [e.item.title for e in digest.entries] == ["Ham 1", "Ham 3", "Ham 4", "Ham 5", "Ham 6"]


def test_parse_replaces_unknown_category():
    data = json.loads(answer())
    data["items"][0]["category"] = "Magazin"
    assert parse_digest(json.dumps(data), ITEMS).entries[0].category == "Endüstri"


def test_parse_caps_number_of_entries():
    assert len(parse_digest(answer(15), ITEMS).entries) == MAX_DIGEST_CARDS


def test_parse_rejects_too_few_items():
    with pytest.raises(ValueError, match="en az"):
        parse_digest(answer(config.MIN_DIGEST_CARDS - 1), ITEMS)


@pytest.mark.parametrize("bad_id", [0, 16, None, "üç"])
def test_parse_rejects_unknown_ids(bad_id):
    data = json.loads(answer())
    data["items"][0]["id"] = bad_id
    with pytest.raises(ValueError, match="numara"):
        parse_digest(json.dumps(data), ITEMS)


@pytest.mark.parametrize("field", ["title", "summary"])
def test_parse_rejects_empty_text(field):
    data = json.loads(answer())
    data["items"][0][field] = "  "
    with pytest.raises(ValueError, match=field):
        parse_digest(json.dumps(data), ITEMS)


def test_parse_rejects_missing_intro():
    with pytest.raises(ValueError, match="intro"):
        parse_digest(answer(intro=""), ITEMS)
