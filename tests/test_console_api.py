"""Unit tests for the read-only console API over a seeded store."""
from __future__ import annotations

import os

from hy3.console.api import ConsoleApi
from hy3.core.store import Store

from console_seed import seed_store

SEED_PATH = None
STORE = None
API = None


def setup_module(module):
    global SEED_PATH, STORE, API
    SEED_PATH = seed_store()
    STORE = Store(SEED_PATH)
    API = ConsoleApi(STORE)


def teardown_module(module):
    global SEED_PATH, STORE
    if STORE is not None:
        STORE.close()
    if SEED_PATH and os.path.exists(SEED_PATH):
        try:
            os.remove(SEED_PATH)
        except OSError:
            pass


def test_sessions_lists_both():
    sessions = API.sessions(limit=100)
    assert {s["id"] for s in sessions} == {"sess_a", "sess_b"}


def test_session_detail_counts_events():
    d = API.session_detail("sess_a")
    assert d is not None
    assert d["id"] == "sess_a"
    assert d["event_count"] == 8  # 7 emitted + 1 ip-result
    assert "aggregated_cost_usd" in d


def test_events_filter_by_kind():
    data = API.events("sess_a", filter="kind:cap.call")
    assert data["filter_errors"] == []
    assert data["count"] == 1
    assert data["events"][0]["kind"] == "cap.call"


def test_events_filter_by_risk():
    data = API.events("sess_a", filter="risk:privileged")
    assert data["count"] == 2  # gate.prompt + gate.approved


def test_events_filter_negation():
    data = API.events("sess_a", filter="!kind:cap.error")
    kinds = {e["kind"] for e in data["events"]}
    assert "cap.error" not in kinds
    assert data["count"] == 7


def test_events_filter_comma_in():
    data = API.events("sess_a", filter="kind:cap.call,cap.result")
    assert data["count"] == 3  # two cap.result + one cap.call


def test_events_filter_entity_substring():
    data = API.events("sess_a", filter="entity:192.168.1.180")
    assert data["count"] >= 1
    assert any("192.168.1.180" in str(e["payload"]) for e in data["events"])


def test_events_filter_free_text():
    data = API.events("sess_a", filter="reboot")
    assert data["count"] == 1
    assert data["events"][0]["kind"] == "gate.prompt"


def test_events_filter_invalid_key_surfaces_error():
    data = API.events("sess_a", filter="bogus:x")
    assert data["filter_errors"]


def test_event_job_context_has_spec_acceptance_diff():
    listing = API.events("sess_a", filter="kind:cap.call")
    eid = listing["events"][0]["id"]
    ev = API.event(eid)
    assert ev is not None
    assert ev["job"] is not None
    job = ev["job"]
    assert job["spec"]["acceptance"]["type"] == "schema"
    assert job["call_inputs"] == {"target": "192.168.1.0/24"}
    assert job["result"] == {"hosts": 12}


def test_runs_and_jobs():
    runs = API.runs(session_id="sess_a")
    assert len(runs) == 1
    jobs = API.jobs("run1")
    assert {j["id"] for j in jobs} == {"j1", "j2", "j3"}


def test_artifacts():
    arts = API.artifacts(session_id="sess_a")
    assert len(arts) == 1
    assert arts[0]["kind"] == "report"


def test_caps_returns_list():
    caps = API.caps()
    assert isinstance(caps, list)
    assert len(caps) >= 1
