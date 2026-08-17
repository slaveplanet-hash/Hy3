"""Read-only console API over the HY3 store (plan §6/§16).

``ConsoleApi`` exposes the data the operator console needs: sessions, the flat
event list (with the Wireshark-style display-filter), single-event detail with
job context (spec / payload / acceptance / diff), runs + jobs, artifacts, and the
capability registry for labeling. Every method returns plain dicts so the HTTP
layer and the tests share one code path — the API never touches sockets.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from hy3.core.store import Store

from .filter import compile_event_filter


def _row_to_dict(row: Any) -> dict:
    """Coerce a ``sqlite3.Row`` (or mapping) into a plain dict."""
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return dict(row)


class ConsoleApi:
    """Stateless read surface over a single :class:`Store`."""

    def __init__(self, store: Store) -> None:
        self.store = store

    # -- sessions --------------------------------------------------------------
    def sessions(self, *, limit: int = 100) -> list[dict]:
        rows = self.store.list_sessions(limit=limit)
        return [_row_to_dict(r) for r in rows]

    def session_detail(self, session_id: str) -> Optional[dict]:
        row = self.store.get_session(session_id)
        if row is None:
            return None
        d = _row_to_dict(row)
        cost, tin, tout = self.store.aggregate_session_cost(session_id)
        d["aggregated_cost_usd"] = round(cost, 6)
        d["aggregated_tokens_in"] = tin
        d["aggregated_tokens_out"] = tout
        d["event_count"] = self.store.conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE session_id = ?", (session_id,)
        ).fetchone()["c"]
        return d

    # -- events (the spine) ----------------------------------------------------
    def events(
        self,
        session_id: str,
        *,
        filter: str = "",
        limit: int = 500,
        query: Optional[str] = None,
    ) -> dict:
        """Return filtered events for a session plus any filter-parse errors."""
        where, params, errors = compile_event_filter(filter or "", session_id=session_id)
        if query:
            # Free-text search overrides a structured filter (uses FTS5).
            rows = self.store.search_events(query, session_id=session_id, limit=limit)
            return {
                "filter_errors": [],
                "search": query,
                "count": len(rows),
                "events": [self._event_view(r) for r in rows],
            }
        sql = (
            f"SELECT * FROM events e WHERE {where} "
            "ORDER BY ts ASC, rowid ASC LIMIT ?"
        )
        params.append(limit)
        rows = self.store.conn.execute(sql, params).fetchall()
        return {
            "filter_errors": errors,
            "count": len(rows),
            "events": [self._event_view(r) for r in rows],
        }

    def event(self, event_id: str) -> Optional[dict]:
        row = self.store.get_event(event_id)
        if row is None:
            return None
        return self._event_view(row, with_job=True)

    # -- runs / jobs ------------------------------------------------------------
    def runs(self, *, session_id: Optional[str] = None) -> list[dict]:
        if session_id is None:
            return []
        rows = self.store.conn.execute(
            "SELECT * FROM runs WHERE session_id = ? ORDER BY started_at ASC",
            (session_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def jobs(self, run_id: str) -> list[dict]:
        rows = self.store.conn.execute(
            "SELECT * FROM jobs WHERE run_id = ? ORDER BY started_at ASC", (run_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # -- artifacts --------------------------------------------------------------
    def artifacts(self, *, session_id: str) -> list[dict]:
        rows = self.store.list_artifacts(session_id)
        return [_row_to_dict(r) for r in rows]

    # -- capabilities (for labeling) -------------------------------------------
    def caps(self) -> list[dict]:
        from hy3.registry import Registry

        reg = Registry.load()
        return [
            {
                "id": c.id,
                "kind": c.kind.value,
                "risk": c.risk.value,
                "summary": c.summary,
                "provenance": c.provenance,
            }
            for c in reg.all()
        ]

    # -- internals --------------------------------------------------------------
    def _event_view(self, row: Any, *, with_job: bool = False) -> dict:
        d = _row_to_dict(row)
        try:
            d["payload"] = json.loads(d["payload"]) if d.get("payload") else {}
        except (ValueError, TypeError):
            d["payload"] = {"_unparseable": True}
        d["redacted"] = bool(d.get("redacted"))
        if with_job and d.get("job_id"):
            d["job"] = self._job_context(d["job_id"])
        return d

    def _job_context(self, job_id: str) -> Optional[dict]:
        """Build the job spec / acceptance / diff detail for an event's job."""
        job = self.store.conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if job is None:
            return None
        job = _row_to_dict(job)
        spec = None
        acceptance = None
        dag = None
        if job.get("run_id"):
            run = self.store.get_run(job["run_id"])
            if run is not None and run["dag_json"]:
                try:
                    dag = json.loads(run["dag_json"])
                except (ValueError, TypeError):
                    dag = None
            if dag and isinstance(dag, dict) and "jobs" in dag:
                for j in dag["jobs"]:
                    if isinstance(j, dict) and j.get("id") == job_id:
                        spec = j
                        acceptance = j.get("acceptance")
                        break
        # inputs (cap.call) vs result (cap.result) for the inline diff.
        call_inputs = None
        result = None
        for e in self.store.conn.execute(
            "SELECT kind, payload FROM events WHERE job_id = ? ORDER BY ts ASC",
            (job_id,),
        ).fetchall():
            try:
                p = json.loads(e["payload"])
            except (ValueError, TypeError):
                continue
            if e["kind"] == "cap.call":
                call_inputs = p.get("inputs")
            elif e["kind"] == "cap.result":
                result = p.get("result")
        return {
            "job": job,
            "spec": spec,
            "acceptance": acceptance,
            "call_inputs": call_inputs,
            "result": result,
            "has_dag": dag is not None,
        }


__all__ = ["ConsoleApi"]
