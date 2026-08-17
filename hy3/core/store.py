"""SQLite store for HY3 Phase 0: connection, migrations, and typed helpers.

No ORM. Every query is plain SQL. The store owns the single connection, keeps
it in WAL mode with foreign keys on and a busy timeout, applies numbered
migrations idempotently, mirrors event payloads into the contentless FTS5
table, and can truncate the WAL via checkpoint().

The caller passes the store explicitly everywhere — there is no global state.
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
import time
from typing import Any, Iterable, Optional

from .ids import ulid

SCHEMA_MIGRATIONS = "schema_migrations"


def now_ms() -> int:
    """Return the current time as integer milliseconds since the Unix epoch (UTC)."""
    return time.time_ns() // 1_000_000


class Store:
    """Thin, explicit wrapper around a single WAL-mode SQLite connection."""

    def __init__(self, path: str, *, check_same_thread: bool = True) -> None:
        """Open (lazily) a store backed by the SQLite file at ``path``.

        ``check_same_thread`` is forwarded to the underlying ``sqlite3.connect``.
        The console passes it ``False`` because its HTTP handler may run on a
        different thread than the one that opened the store; for the read-only
        console this is safe.
        """
        self.path = os.path.abspath(path)
        self.root = os.path.dirname(self.path)
        self._check_same_thread = check_same_thread
        self._conn: Optional[sqlite3.Connection] = None

    # -- connection lifecycle --------------------------------------------------
    @property
    def conn(self) -> sqlite3.Connection:
        """Return the live connection, opening and configuring it on first use."""
        if self._conn is None:
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=self._check_same_thread)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            self._conn = conn
        return self._conn

    def close(self) -> None:
        """Close the underlying connection if open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def checkpoint(self, mode: str = "TRUNCATE") -> None:
        """Truncate the WAL, folding committed frames back into the main db file."""
        # mode is a fixed keyword (PASSIVE|FULL|RESTART|TRUNCATE), not user input.
        self.conn.execute(f"PRAGMA wal_checkpoint({mode})")

    # -- migrations ------------------------------------------------------------
    def migrate(self, migrations_dir: str) -> list[str]:
        """Apply every numbered ``NNN_*.sql`` migration once, in version order.

        Returns the list of version numbers actually applied on this call. Re-running
        is a no-op: applied versions are recorded in ``schema_migrations``.
        """
        conn = self.conn
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {SCHEMA_MIGRATIONS} "
            f"(version TEXT PRIMARY KEY, applied_at INTEGER NOT NULL, name TEXT)"
        )
        conn.commit()
        applied = {
            r["version"]
            for r in conn.execute(f"SELECT version FROM {SCHEMA_MIGRATIONS}").fetchall()
        }
        files = sorted(
            glob.glob(os.path.join(migrations_dir, "[0-9]*_*.sql")),
            key=lambda p: os.path.basename(p).split("_", 1)[0],
        )
        ran: list[str] = []
        for path in files:
            version = os.path.basename(path).split("_", 1)[0]
            if version in applied:
                continue
            with open(path, "r", encoding="utf-8") as fh:
                sql = fh.read()
            conn.executescript(sql)
            conn.execute(
                f"INSERT INTO {SCHEMA_MIGRATIONS}(version, applied_at, name) VALUES (?, ?, ?)",
                (version, now_ms(), os.path.basename(path)),
            )
            conn.commit()
            applied.add(version)
            ran.append(version)
        return ran

    # -- events (the spine) ----------------------------------------------------
    def insert_event(
        self,
        *,
        session_id: str,
        kind: str,
        payload: Any,
        run_id: Optional[str] = None,
        job_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        provider: Optional[str] = None,
        risk: Optional[str] = None,
        redacted: bool = False,
        ts: Optional[int] = None,
    ) -> tuple[str, int]:
        """Insert one append-only event and mirror its payload into events_fts.

        Returns ``(event_id, rowid)``. The rowid is the integer join key back to
        the contentless FTS table. Payloads that are not JSON-serializable raise
        ``ValueError`` loudly rather than being silently dropped.
        """
        try:
            blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"event payload is not JSON-serializable: {exc}") from exc
        event_id = ulid()
        ts = ts if ts is not None else now_ms()
        cur = self.conn.execute(
            "INSERT INTO events(id, session_id, run_id, job_id, ts, kind, "
            "capability_id, provider, risk, payload, redacted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                session_id,
                run_id,
                job_id,
                ts,
                kind,
                capability_id,
                provider,
                risk,
                blob,
                1 if redacted else 0,
            ),
        )
        rowid = cur.lastrowid
        # Contentless FTS5: write with explicit rowid == events.rowid.
        self.conn.execute(
            "INSERT INTO events_fts(rowid, body) VALUES (?, ?)", (rowid, blob)
        )
        self.conn.commit()
        return event_id, rowid

    def get_event(self, event_id: str) -> Optional[sqlite3.Row]:
        """Fetch a single event by id, or None."""
        return self.conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()

    def list_events(
        self,
        *,
        session_id: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        """List events ordered by (ts, rowid); optionally filtered by session/kind."""
        sql = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if session_id is not None:
            sql += " AND session_id = ?"
            params.append(session_id)
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY ts ASC, rowid ASC LIMIT ?"
        params.append(limit)
        return self.conn.execute(sql, params).fetchall()

    def search_events(
        self, query: str, *, session_id: Optional[str] = None, limit: int = 200
    ) -> list[sqlite3.Row]:
        """Full-text search over event payloads via events_fts.

        Each whitespace-separated term is matched as a quoted phrase joined with AND,
        so multi-word queries require all terms to be present.
        """
        fts = self._fts_query(query)
        # FTS5 requires MATCH on the (unaliased) virtual table name.
        sql = (
            "SELECT e.* FROM events e "
            "JOIN events_fts ON events_fts.rowid = e.rowid "
            "WHERE events_fts MATCH ?"
        )
        params: list[Any] = [fts]
        if session_id is not None:
            sql += " AND e.session_id = ?"
            params.append(session_id)
        sql += " ORDER BY e.ts ASC LIMIT ?"
        params.append(limit)
        return self.conn.execute(sql, params).fetchall()

    @staticmethod
    def _fts_query(text: str) -> str:
        """Build a safe FTS5 MATCH expression from free text (terms AND-ed)."""
        terms = [t for t in text.split() if t]
        if not terms:
            return '""'  # match nothing
        return " AND ".join('"%s"' % t.replace('"', '""') for t in terms)

    # -- sessions --------------------------------------------------------------
    def insert_session(self, row: dict[str, Any]) -> None:
        """Insert a sessions row from a dict of column->value."""
        self._insert("sessions", row)

    def update_session_end(
        self,
        session_id: str,
        status: str,
        ended_at: int,
        cost_usd: float,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        """Stamp a session as ended and write accumulated cost/token totals."""
        self.conn.execute(
            "UPDATE sessions SET status=?, ended_at=?, cost_usd=?, tokens_in=?, "
            "tokens_out=? WHERE id=?",
            (status, ended_at, cost_usd, tokens_in, tokens_out, session_id),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> Optional[sqlite3.Row]:
        """Fetch a single session by id, or None."""
        return self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

    def list_sessions(self, limit: int = 100) -> list[sqlite3.Row]:
        """List sessions ordered by start time, newest first."""
        return self.conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()

    def aggregate_session_cost(self, session_id: str) -> tuple[float, int, int]:
        """Best-effort sum of cost/tokens from event payloads (usage blocks).

        # UNCERTAIN: which exact payload keys carry usage is settled in Phase 2
        # (model.response / cap.result). We sum any numeric cost_usd/tokens_in/
        # tokens_out we find; unknown shapes are skipped.
        """
        cost = 0.0
        tin = 0
        tout = 0
        for r in self.conn.execute(
            "SELECT payload FROM events WHERE session_id = ?", (session_id,)
        ).fetchall():
            try:
                p = json.loads(r["payload"])
            except (ValueError, TypeError):
                continue
            if isinstance(p, dict):
                cost += float(p.get("cost_usd") or 0)
                tin += int(p.get("tokens_in") or 0)
                tout += int(p.get("tokens_out") or 0)
        return cost, tin, tout

    # -- runs / jobs -----------------------------------------------------------
    def insert_run(self, row: dict[str, Any]) -> None:
        """Insert a runs row from a dict of column->value."""
        self._insert("runs", row)

    def get_run(self, run_id: str) -> Optional[sqlite3.Row]:
        """Fetch a single run by id, or None."""
        return self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()

    def insert_job(self, row: dict[str, Any]) -> None:
        """Insert a jobs row from a dict of column->value."""
        self._insert("jobs", row)

    def update_job(self, job_id: str, status: str, ended_at: Optional[int]) -> None:
        """Update a job's status and (optionally) end time."""
        self.conn.execute(
            "UPDATE jobs SET status=?, ended_at=? WHERE id=?",
            (status, ended_at, job_id),
        )
        self.conn.commit()

    # -- artifacts -------------------------------------------------------------
    def insert_artifact(self, row: dict[str, Any]) -> None:
        """Insert an artifacts row from a dict of column->value."""
        self._insert("artifacts", row)

    def get_artifact(self, artifact_id: str) -> Optional[sqlite3.Row]:
        """Fetch a single artifact by id, or None."""
        return self.conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()

    def get_artifact_by_sha(self, sha256: str) -> Optional[sqlite3.Row]:
        """Fetch the first artifact row with the given content hash, or None."""
        return self.conn.execute(
            "SELECT * FROM artifacts WHERE sha256 = ? LIMIT 1", (sha256,)
        ).fetchone()

    def list_artifacts(self, session_id: str) -> list[sqlite3.Row]:
        """List artifacts for a session ordered by creation time."""
        return self.conn.execute(
            "SELECT * FROM artifacts WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()

    # -- cross-reference / memory / skills (helpers exist; extraction is Phase 4) -
    def insert_entity(self, row: dict[str, Any]) -> None:
        """Insert an entities row from a dict of column->value."""
        self._insert("entities", row)

    def get_entity_by_norm(self, kind: str, norm: str) -> Optional[sqlite3.Row]:
        """Fetch an entity by (kind, norm), or None."""
        return self.conn.execute(
            "SELECT * FROM entities WHERE kind = ? AND norm = ?", (kind, norm)
        ).fetchone()

    def insert_mention(self, row: dict[str, Any]) -> None:
        """Insert a mentions row from a dict of column->value."""
        self._insert("mentions", row)

    def insert_edge(self, row: dict[str, Any]) -> None:
        """Insert an edges row from a dict of column->value."""
        self._insert("edges", row)

    def insert_memory(self, row: dict[str, Any]) -> None:
        """Insert a memories row from a dict of column->value."""
        self._insert("memories", row)

    def insert_skill(self, row: dict[str, Any]) -> None:
        """Insert a skills row from a dict of column->value."""
        self._insert("skills", row)

    # -- internal --------------------------------------------------------------
    def _insert(self, table: str, row: dict[str, Any]) -> None:
        """Generic typed INSERT for a row dict; commits immediately."""
        if not row:
            raise ValueError(f"cannot insert empty row into {table}")
        cols = list(row.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_sql = ", ".join(cols)
        self.conn.execute(
            f"INSERT INTO {table}({col_sql}) VALUES ({placeholders})",
            [row[c] for c in cols],
        )
        self.conn.commit()
