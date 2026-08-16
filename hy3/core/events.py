"""Append-only event writer and the closed ``EventKind`` set (plan §4).

Events are the product (principle P2): every action is written before it is
acted on. The critical ordering rule is that ``cap.call`` is committed *before*
the wrapped capability runs, so a crash mid-action still records what it was
doing. ``EventWriter.call`` enforces this with a context manager — it is not
possible to invoke the capability before the call event exists.
"""
from __future__ import annotations

import traceback
from contextlib import contextmanager
from enum import StrEnum
from typing import Any, Iterator, Optional

from .store import Store


class EventKind(StrEnum):
    """Closed set of event kinds. Add deliberately; do not widen casually."""

    SESSION_START = "session.start"
    SESSION_END = "session.end"
    PLAN_PROPOSED = "plan.proposed"
    PLAN_REVISED = "plan.revised"
    JOB_START = "job.start"
    JOB_END = "job.end"
    CAP_CALL = "cap.call"
    CAP_RESULT = "cap.result"
    CAP_ERROR = "cap.error"
    MODEL_REQUEST = "model.request"
    MODEL_RESPONSE = "model.response"
    ACCEPT_PASS = "accept.pass"
    ACCEPT_FAIL = "accept.fail"
    GATE_PROMPT = "gate.prompt"
    GATE_APPROVED = "gate.approved"
    GATE_DENIED = "gate.denied"
    EGRESS_ALLOW = "egress.allow"
    EGRESS_BLOCK = "egress.block"
    SNAPSHOT_TAKEN = "snapshot.taken"
    ROLLBACK_RUN = "rollback.run"
    SKILL_PROPOSED = "skill.proposed"
    SKILL_PROMOTED = "skill.promoted"
    SKILL_DEPRECATED = "skill.deprecated"
    BUDGET_EXCEEDED = "budget.exceeded"
    ABORT = "abort"


class EventWriter:
    """Emits events into a store for one session (and optional run/job context)."""

    def __init__(
        self,
        store: Store,
        session_id: str,
        *,
        run_id: Optional[str] = None,
        job_id: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> None:
        """Bind the writer to a session; run/job/provider become defaults for emit."""
        self.store = store
        self.session_id = session_id
        self.run_id = run_id
        self.job_id = job_id
        self.provider = provider

    def emit(
        self,
        kind: "EventKind | str",
        *,
        run_id: Optional[str] = None,
        job_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        provider: Optional[str] = None,
        risk: Optional[str] = None,
        payload: Any = None,
        redacted: bool = False,
    ) -> str:
        """Write one event and return its id. Payload must be JSON-serializable."""
        kind_str = kind.value if isinstance(kind, EventKind) else str(kind)
        event_id, _ = self.store.insert_event(
            session_id=self.session_id,
            kind=kind_str,
            payload=payload if payload is not None else {},
            run_id=run_id or self.run_id,
            job_id=job_id or self.job_id,
            capability_id=capability_id,
            provider=provider or self.provider,
            risk=risk,
            redacted=redacted,
        )
        return event_id

    @contextmanager
    def call(
        self,
        capability_id: str,
        inputs: Any,
        *,
        risk: Optional[str] = None,
        provider: Optional[str] = None,
        job_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Iterator["_CallHandle"]:
        """Context manager that commits ``cap.call`` BEFORE the capability runs.

        Usage::

            with writer.call(capability_id, inputs) as call:
                result = run_capability(inputs)
                call.ok(result)

        On exception, a ``cap.error`` event carrying the traceback is emitted and
        the exception is re-raised. ``call.ok(result)`` emits ``cap.result``.
        """
        rid = run_id or self.run_id
        jid = job_id or self.job_id
        prov = provider or self.provider
        # Commit cap.call now, before any user code runs (durability guarantee).
        cap_event_id = self.emit(
            EventKind.CAP_CALL,
            capability_id=capability_id,
            provider=prov,
            risk=risk,
            job_id=jid,
            run_id=rid,
            payload={"inputs": inputs},
        )
        handle = _CallHandle(
            writer=self,
            capability_id=capability_id,
            provider=prov,
            risk=risk,
            job_id=jid,
            run_id=rid,
            cap_event_id=cap_event_id,
        )
        try:
            yield handle
        except Exception as exc:
            self.emit(
                EventKind.CAP_ERROR,
                capability_id=capability_id,
                provider=prov,
                risk=risk,
                job_id=jid,
                run_id=rid,
                payload={
                    "cap_call_id": cap_event_id,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            raise


class _CallHandle:
    """Returned by ``EventWriter.call``; call ``.ok(result)`` to record success."""

    def __init__(
        self,
        *,
        writer: EventWriter,
        capability_id: str,
        provider: Optional[str],
        risk: Optional[str],
        job_id: Optional[str],
        run_id: Optional[str],
        cap_event_id: str,
    ) -> None:
        self._writer = writer
        self._capability_id = capability_id
        self._provider = provider
        self._risk = risk
        self._job_id = job_id
        self._run_id = run_id
        self.cap_event_id = cap_event_id

    def ok(self, result: Any) -> str:
        """Emit ``cap.result`` for the preceding ``cap.call`` and return its id."""
        return self._writer.emit(
            EventKind.CAP_RESULT,
            capability_id=self._capability_id,
            provider=self._provider,
            risk=self._risk,
            job_id=self._job_id,
            run_id=self._run_id,
            payload={"cap_call_id": self.cap_event_id, "result": result},
        )
