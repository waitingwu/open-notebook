import json

import pytest

from open_notebook.exceptions import InvalidInputError
from open_notebook.repo_kb.native_compile import citation_aliases, expand_aliases


def test_compiler_source_ids_expand_only_to_verified_input_references():
    ref = "〔docs:spec.doc#L1-L40@abcdef12〕"
    context, aliases = citation_aliases(ref + "\nL1: 檢查來源")
    assert "〔S1〕" in context
    assert expand_aliases("步驟〔S1〕", aliases) == "步驟" + ref
    with pytest.raises(InvalidInputError):
        expand_aliases("偽造來源〔S999〕", aliases)


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
