import json

import pytest

from open_notebook.repo_kb.retrieve import entity_pages, parse_selection


def test_selection_rejects_unknown_scope_and_never_guesses_free_text():
    allowed = {"modules/A0", "flows/new-contract", "qa/previous"}
    assert parse_selection('{"pages":["modules/A0","modules/A0"]}', allowed) == [
        "modules/A0"
    ]
    for answer in (
        "modules/A0",
        '{"pages":[]}',
        '{"pages":["../../secret"]}',
        '{"pages":["another-kb/qa"]}',
        json.dumps({"pages": ["modules/A0"] * 9}),
        '{"pages":["modules/A0"],"command":"read"}',
    ):
        with pytest.raises(ValueError):
            parse_selection(answer, allowed)


def test_entities_find_table_and_module_without_listing_all_tables_to_model():
    pages = [
        {
            "slug": "tables/DTAV0011_AA",
            "kind": "table",
            "title": "DTAV0011_AA",
            "summary": "資料表",
        },
        {"slug": "modules/A0", "kind": "module", "title": "A0", "summary": "新契約"},
        {"slug": "qa/old", "kind": "qa", "title": "其他問題", "summary": "摘要"},
    ]
    assert entity_pages("A0 如何使用 DTAV0011_AA？", pages) == [
        "tables/DTAV0011_AA",
        "modules/A0",
    ]
