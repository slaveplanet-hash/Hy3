"""Unit tests for the Wireshark-style display-filter parser/compiler."""
from __future__ import annotations

import pytest

from hy3.console.filter import compile_event_filter, parse_filter


def test_empty_query_is_empty():
    pf = parse_filter("")
    assert pf.is_empty
    assert pf.clauses == []
    assert pf.errors == []


def test_equality_clause():
    pf = parse_filter("kind:cap.call")
    assert len(pf.clauses) == 1
    assert pf.clauses[0].key == "kind"
    assert pf.clauses[0].value == "cap.call"
    assert pf.clauses[0].negate is False
    where, params, errs = compile_event_filter("kind:cap.call")
    assert errs == []
    assert where == "e.kind = ?"
    assert params == ["cap.call"]


def test_comma_in_list_compiles_to_in():
    where, params, errs = compile_event_filter("kind:cap.call,cap.result")
    assert errs == []
    assert "e.kind IN (" in where
    assert params == ["cap.call", "cap.result"]


def test_negation_prefix():
    where, params, errs = compile_event_filter("!kind:cap.error")
    assert errs == []
    assert "(e.kind IS NULL OR e.kind != ?)" == where
    assert params == ["cap.error"]


def test_negation_operator_form():
    where, params, errs = compile_event_filter("kind!=cap.error")
    assert errs == []
    assert "(e.kind IS NULL OR e.kind != ?)" == where
    assert params == ["cap.error"]


def test_column_keys_map():
    where, params, _ = compile_event_filter("capability:net.scan risk:write provider:lm-studio")
    assert "e.capability_id = ?" in where
    assert "e.risk = ?" in where
    assert "e.provider = ?" in where
    assert params == ["net.scan", "write", "lm-studio"]


def test_entity_and_text_are_payload_substring():
    where, params, errs = compile_event_filter("entity:192.168.1.180 text:\"dns query\"")
    assert errs == []
    assert where.count("e.payload LIKE ? ESCAPE '\\'") == 2
    # quotes stripped, wildcards escaped
    assert "%192.168.1.180%" in params[0]
    assert "%dns query%" in params[1]


def test_free_text_terms():
    where, params, _ = compile_event_filter("reboot router")
    assert where.count("e.payload LIKE ? ESCAPE '\\'") == 2
    assert "%reboot%" in params[0]
    assert "%router%" in params[1]


def test_like_wildcards_are_escaped():
    # A user value containing %/_ must not become a SQL wildcard.
    where, params, _ = compile_event_filter("text:100%")
    assert "%100\\%%" in params[0]


def test_unknown_key_reports_error_but_still_runs():
    pf = parse_filter("bogus:x")
    assert pf.errors
    where, params, errs = compile_event_filter("bogus:x")
    assert errs  # surfaced to the UI
    assert where == "1=1"  # no harmful clause added
    assert params == []


def test_session_scope_is_anded():
    where, params, _ = compile_event_filter("kind:cap.call", session_id="sess_a")
    assert "e.session_id = ?" in where
    assert "e.kind = ?" in where
    assert params == ["sess_a", "cap.call"]


def test_quoted_value_keeps_spaces():
    pf = parse_filter('text:"dns query"')
    assert pf.free == []
    assert pf.clauses[0].value == "dns query"
