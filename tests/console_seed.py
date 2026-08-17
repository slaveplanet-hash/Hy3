"""Shared seed for console tests — builds a temp store with realistic Phase 0-3 data.

Run from the repo root (pytest's cwd). The migrations dir is resolved relative to
this file so the seed works regardless of where pytest is invoked.
"""
from __future__ import annotations

import json
import os
import tempfile

from hy3.core.events import EventKind, EventWriter
from hy3.core.store import Store

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(REPO_ROOT, "migrations")


def seed_store() -> str:
    """Create a temp hy3.db, seed it, and return its path."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="hy3_console_test_")
    os.close(fd)
    os.remove(path)  # Store() will (re)create it on migrate
    store = Store(path)
    store.migrate(MIGRATIONS_DIR)

    store.insert_session({
        "id": "sess_a", "parent_id": None, "title": "Net audit",
        "goal": "Audit LAN for exposures", "status": "done",
        "started_at": 1000, "ended_at": 2000, "cost_usd": 0.0,
        "tokens_in": 0, "tokens_out": 0, "tags": json.dumps(["net"]),
    })
    store.insert_session({
        "id": "sess_b", "parent_id": None, "title": "Research",
        "goal": "Deep research on X", "status": "running",
        "started_at": 3000, "ended_at": None, "cost_usd": 0.0,
        "tokens_in": 0, "tokens_out": 0, "tags": json.dumps([]),
    })

    w = EventWriter(store, "sess_a")
    w.emit(EventKind.SESSION_START, payload={"goal": "Audit LAN for exposures"})
    w.emit(EventKind.CAP_CALL, capability_id="net.scan.lan", risk="read",
           provider="lm-studio", job_id="j1", payload={"inputs": {"target": "192.168.1.0/24"}})
    w.emit(EventKind.CAP_RESULT, capability_id="net.scan.lan", risk="read",
           job_id="j1", payload={"result": {"hosts": 12}})
    w.emit(EventKind.CAP_ERROR, capability_id="net.scan.lan", risk="read",
           job_id="j2", payload={"error": "timeout", "traceback": "..."})
    w.emit(EventKind.GATE_PROMPT, capability_id="net.restart", risk="privileged",
           job_id="j3", payload={"prompt": "reboot router?"})
    w.emit(EventKind.GATE_APPROVED, capability_id="net.restart", risk="privileged",
           job_id="j3", payload={"reason": "user ok"})
    w.emit(EventKind.ACCEPT_FAIL, capability_id="net.scan.lan", risk="read",
           job_id="j1", payload={"why": "schema"})
    # A result event whose payload contains an entity IP (exercises `entity:` filter).
    e_ip = w.emit(EventKind.CAP_RESULT, capability_id="net.scan.lan", risk="read",
                  payload={"result": {"host": "192.168.1.180", "open_ports": [22, 80]}})

    # Cross-reference tables (exercise store helpers; entity filter also matches via payload).
    store.insert_entity({
        "id": "ent1", "kind": "ip", "value": "192.168.1.180", "norm": "192.168.1.180",
        "first_seen": 1000, "last_seen": 2000,
    })
    store.insert_mention({
        "entity_id": "ent1", "event_id": e_ip, "session_id": "sess_a", "ts": 1500,
    })

    store.insert_run({
        "id": "run1", "session_id": "sess_a",
        "dag_json": json.dumps({"jobs": [
            {"id": "j1", "capability_id": "net.scan.lan", "profile": "analyst",
             "depends_on": [], "risk": "read",
             "acceptance": {"type": "schema", "schema": {"hosts": "number"}}},
            {"id": "j2", "capability_id": "net.scan.lan", "profile": "analyst",
             "depends_on": ["j1"], "risk": "read", "acceptance": {"type": "none"}},
            {"id": "j3", "capability_id": "net.restart", "profile": "boss",
             "depends_on": [], "risk": "privileged", "acceptance": {"type": "none"}},
        ]}),
        "budget_json": json.dumps({"max_steps": 10, "max_usd": 1.0, "wall_clock_s": 60}),
        "outcome": "partial", "started_at": 1000, "ended_at": 2000,
    })
    for jid, cap, prof, dep, risk in [
        ("j1", "net.scan.lan", "analyst", [], "read"),
        ("j2", "net.scan.lan", "analyst", ["j1"], "read"),
        ("j3", "net.restart", "boss", [], "privileged"),
    ]:
        store.insert_job({
            "id": jid, "run_id": "run1", "capability_id": cap, "profile": prof,
            "depends_on": json.dumps(dep), "status": "passed", "attempt": 1,
            "risk": risk, "started_at": 1000, "ended_at": 1500,
        })
    store.insert_artifact({
        "id": "a1", "session_id": "sess_a", "job_id": "j1", "sha256": "deadbeef",
        "path": "/tmp/a1.json", "kind": "report", "bytes": 42, "created_at": 1500,
    })
    store.close()
    return path
