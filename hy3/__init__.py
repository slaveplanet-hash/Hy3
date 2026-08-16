"""HY3 — local-first agent harness for PC management, network engineering, and deep research.

Phase 0 delivers the storage spine and session lifecycle only:
migrations, a SQLite store (WAL + FTS5), an append-only event writer,
session create/resume/fork/end, and a content-addressed artifact store.

No orchestrator, no capabilities, no providers, no UI — those are Phase 1+.
"""

__version__ = "0.1.1"
