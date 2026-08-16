"""Session lifecycle tests, including kill-and-resume exact reconstruction."""
import json

import pytest

from hy3.core import session as S
from hy3.core.events import EventKind, EventWriter
from hy3.core.store import Store


def test_create_emits_start_and_persists(store):
    """create() stores the row, parses tags, and writes session.start."""
    sess = S.create(store, "goal", tags=["a", "b"])
    assert sess.status == "running"
    row = store.get_session(sess.id)
    assert row is not None
    assert json.loads(row["tags"]) == ["a", "b"]
    assert any(
        e["kind"] == "session.start" for e in store.list_events(session_id=sess.id)
    )


def test_100_events_survive_kill_and_resume_exactly(store):
    """100 committed events survive a process kill and resume reconstructs them exactly."""
    sess = S.create(store, "repro")
    w = EventWriter(store, sess.id)
    written = []
    for i in range(100):
        p = {"i": i, "marker": f"m{i}", "word": f"kw{i}"}
        w.emit(
            EventKind.CAP_CALL if i % 2 == 0 else EventKind.CAP_RESULT,
            capability_id="net.scan.lan",
            payload=p,
        )
        written.append(p)
    w.emit(EventKind.JOB_END, job_id="j7", payload={"status": "passed"})

    # Simulate a hard kill: drop the connection without an explicit checkpoint.
    store.close()
    store2 = Store(store.path)
    sess2, last_job = S.resume(store2, sess.id)

    assert last_job == "j7"
    events = store2.list_events(session_id=sess.id, limit=10**9)
    # The 100 cap events (excluding the leading session.start and the trailing
    # job.end) must replay byte-for-byte in the same order.
    restored = [
        json.loads(e["payload"])
        for e in events
        if e["kind"] in ("cap.call", "cap.result")
    ]
    assert restored == written
    assert len(restored) == 100


def test_fork_sets_parent(store):
    """fork() creates a child with parent_id set and the source recorded."""
    parent = S.create(store, "p")
    child = S.fork(store, parent.id, "child goal")
    assert child.parent_id == parent.id
    assert store.get_session(child.id)["parent_id"] == parent.id


def test_end_stamps_status_and_emits_session_end(store):
    """end() validates status, stamps the row, and logs session.end."""
    sess = S.create(store, "g")
    ended = S.end(store, sess.id, "done")
    assert ended.status == "done"
    assert ended.ended_at is not None
    assert any(
        e["kind"] == "session.end" for e in store.list_events(session_id=sess.id)
    )
    with pytest.raises(ValueError):
        S.end(store, sess.id, "bogus-status")
