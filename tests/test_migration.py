"""Migration runner idempotency and completeness."""
import os

from hy3.core.store import Store, SCHEMA_MIGRATIONS

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")

EXPECTED_TABLES = {
    "sessions", "runs", "jobs", "events", "events_fts", "artifacts",
    "entities", "mentions", "edges", "memories", "skills", SCHEMA_MIGRATIONS,
}


def test_migrate_twice_is_idempotent(store: Store):
    """Applying the migration twice errors neither creates duplicate tables nor re-inserts."""
    # First apply already happened in the fixture. Apply again explicitly.
    applied = store.migrate(MIGRATIONS_DIR)
    assert applied == []  # nothing new applied on second run

    names = {
        r["name"]
        for r in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for t in EXPECTED_TABLES:
        assert t in names
    # No duplicate 'sessions' table (would appear as two rows).
    assert sum(1 for n in names if n == "sessions") == 1

    rows = store.conn.execute(
        f"SELECT version FROM {SCHEMA_MIGRATIONS} ORDER BY version"
    ).fetchall()
    assert [r["version"] for r in rows] == ["001"]


def test_wal_and_foreign_keys_enabled(store: Store):
    """The connection runs in WAL mode with foreign keys enforced."""
    journal = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal.lower() == "wal"
    fk = store.conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
