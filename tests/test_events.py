"""EventWriter tests: cap.call ordering, exception path, FTS, payload safety."""
import json
import sqlite3

import pytest

from hy3.core import session as S
from hy3.core.events import EventKind, EventWriter


def test_cap_call_visible_before_callable_returns(store):
    """cap.call is committed (and visible to a fresh connection) before the body runs."""
    sess = S.create(store, "g")
    w = EventWriter(store, sess.id, provider="local")
    seen = {}

    def work():
        # A brand-new connection must already see the cap.call row.
        c = sqlite3.connect(store.path)
        row = c.execute(
            "SELECT id FROM events WHERE kind='cap.call' AND capability_id=?",
            ("net.scan.lan",),
        ).fetchone()
        seen["present"] = row is not None

    with w.call("net.scan.lan", {"iface": "Wi-Fi"}) as call:
        work()  # assert from inside the callable, as required
        call.ok({"hosts": 3})

    assert seen["present"] is True
    assert (
        store.conn.execute("SELECT 1 FROM events WHERE kind='cap.result'").fetchone()
        is not None
    )


def test_call_emits_cap_error_and_reraises(store):
    """An exception inside writer.call emits cap.error (with traceback) and re-raises."""
    sess = S.create(store, "g")
    w = EventWriter(store, sess.id)
    with pytest.raises(ValueError):
        with w.call("pc.svc.restart", {}) as call:
            raise ValueError("boom")
    err = store.conn.execute(
        "SELECT payload FROM events WHERE kind='cap.error'"
    ).fetchone()
    assert err is not None
    assert "boom" in err["payload"]
    assert "Traceback" in err["payload"]  # traceback is captured


def test_fts_returns_only_matching_event(store):
    """A term present in exactly one payload returns exactly that event."""
    sess = S.create(store, "g")
    w = EventWriter(store, sess.id)
    w.emit(EventKind.MODEL_RESPONSE, payload={"note": "unicorn42xyz alpha"})
    w.emit(EventKind.MODEL_RESPONSE, payload={"note": "dragon99abc beta"})
    hits = store.search_events("unicorn42xyz")
    assert len(hits) == 1
    assert "unicorn42xyz" in hits[0]["payload"]


def test_non_serializable_payload_rejected(store):
    """A payload that is not JSON-serializable raises loudly instead of being dropped."""
    sess = S.create(store, "g")
    w = EventWriter(store, sess.id)
    with pytest.raises(ValueError):
        w.emit(EventKind.CAP_CALL, payload={"bad": object()})
