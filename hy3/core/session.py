"""Session lifecycle for HY3 Phase 0: create, resume, fork, end.

Sessions own the append-only event stream. ``resume`` rebuilds in-memory state by
replaying events (so a killed process can continue instead of redo), and returns
the last completed job id. ``fork`` starts a child session that shares artifacts
by content hash — bytes are never copied.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from .events import EventKind, EventWriter
from .ids import ulid
from .store import Store, now_ms

VALID_STATUS = {"planning", "running", "paused", "done", "failed", "aborted"}


@dataclass
class Session:
    """In-memory view of a ``sessions`` row."""

    id: str
    goal: str
    status: str
    started_at: int
    title: Optional[str] = None
    parent_id: Optional[str] = None
    ended_at: Optional[int] = None
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    tags: list[str] = None  # type: ignore[assignment]


def _row_to_session(row: Any) -> Session:
    """Build a ``Session`` from a sqlite3.Row, parsing the tags JSON array."""
    tags = None
    if row["tags"]:
        try:
            tags = json.loads(row["tags"])
        except (ValueError, TypeError):
            tags = None
    return Session(
        id=row["id"],
        goal=row["goal"],
        status=row["status"],
        started_at=row["started_at"],
        title=row["title"],
        parent_id=row["parent_id"],
        ended_at=row["ended_at"],
        cost_usd=row["cost_usd"] or 0.0,
        tokens_in=row["tokens_in"] or 0,
        tokens_out=row["tokens_out"] or 0,
        tags=tags or [],
    )


def create(
    store: Store,
    goal: str,
    *,
    parent_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    title: Optional[str] = None,
) -> Session:
    """Create a new session, persist it, and emit ``session.start``.

    Initial status is ``running`` (the session is live and will collect events).
    """
    sid = ulid()
    ts = now_ms()
    row = {
        "id": sid,
        "parent_id": parent_id,
        "title": title,
        "goal": goal,
        "status": "running",
        "started_at": ts,
        "ended_at": None,
        "cost_usd": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "tags": json.dumps(tags or []),
    }
    store.insert_session(row)
    writer = EventWriter(store, sid)
    writer.emit(
        EventKind.SESSION_START,
        payload={"goal": goal, "tags": tags or [], "forked_from": parent_id},
    )
    return _row_to_session(row)


def resume(store: Store, session_id: str) -> tuple[Session, Optional[str]]:
    """Replay a session's events to rebuild state; return (session, last_completed_job_id).

    The last completed job is the most recent ``job.end`` whose payload status is
    ``passed`` (by ts/rowid order), so a future scheduler can continue past it.
    """
    row = store.get_session(session_id)
    if row is None:
        raise ValueError(f"no such session: {session_id}")
    events = store.list_events(session_id=session_id, limit=1_000_000)
    last_job_id: Optional[str] = None
    for ev in events:
        if ev["kind"] == EventKind.JOB_END:
            try:
                payload = json.loads(ev["payload"])
            except (ValueError, TypeError):
                payload = {}
            if payload.get("status") == "passed":
                # ts/rowid order from list_events guarantees the latest wins.
                last_job_id = ev["job_id"]
    return _row_to_session(row), last_job_id


def fork(store: Store, session_id: str, goal: str) -> Session:
    """Create a child session of ``session_id`` with ``parent_id`` set.

    Artifacts are shared by content hash: the child references the same files via
    ``get_by_sha`` and no artifact bytes (or rows) are copied. Emits ``session.start``
    recording the fork source.
    """
    parent = store.get_session(session_id)
    if parent is None:
        raise ValueError(f"no such session to fork: {session_id}")
    tags = None
    if parent["tags"]:
        try:
            tags = json.loads(parent["tags"])
        except (ValueError, TypeError):
            tags = None
    child = create(store, goal, parent_id=session_id, tags=tags)
    writer = EventWriter(store, child.id)
    writer.emit(
        EventKind.SESSION_START,
        payload={"goal": goal, "forked_from": session_id},
    )
    return child


def end(store: Store, session_id: str, status: str) -> Session:
    """Mark a session ended: stamp status/ended_at and accumulate cost/tokens.

    # UNCERTAIN: cost/token totals are best-effort sums read from event payloads
    (model.response / cap.result usage blocks); the exact key names are finalized
    in Phase 2. Always emits ``session.end`` so the closure is in the log.
    """
    if status not in VALID_STATUS:
        raise ValueError(f"invalid session status: {status!r}")
    row = store.get_session(session_id)
    if row is None:
        raise ValueError(f"no such session: {session_id}")
    ended_at = now_ms()
    cost_usd, tokens_in, tokens_out = store.aggregate_session_cost(session_id)
    store.update_session_end(session_id, status, ended_at, cost_usd, tokens_in, tokens_out)
    writer = EventWriter(store, session_id)
    writer.emit(
        EventKind.SESSION_END,
        payload={
            "status": status,
            "cost_usd": cost_usd,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        },
    )
    updated = store.get_session(session_id)
    return _row_to_session(updated)
