"""Shared pytest fixtures for HY3 Phase 0 tests."""
import os
import tempfile

import pytest

from hy3.core.store import Store

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(REPO_ROOT, "migrations")


@pytest.fixture
def store() -> Store:
    """Yield a migrated Store backed by a temp db; close it afterwards."""
    d = tempfile.mkdtemp()
    db = os.path.join(d, "hy3.db")
    s = Store(db)
    s.migrate(MIGRATIONS_DIR)
    yield s
    s.close()
