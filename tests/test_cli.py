"""Regression tests for the hy3 CLI (bin/hy3.py).

These exercise the command-line entry points as subprocesses so that argument
parsing and dispatch bugs (e.g. a missing --limit on `session list`) are caught
even though the core logic is already covered by the unit tests.
"""
from __future__ import annotations

import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(REPO_ROOT, "bin", "hy3.py")


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run the CLI with ``args`` in ``cwd`` and return the completed process."""
    return subprocess.run(
        [sys.executable, CLI, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_cli_session_list_and_end_to_end(tmp_path: object) -> None:
    """init -> new -> list -> show -> events tail -> search all exit 0."""
    cwd = str(tmp_path)
    db = os.path.join(cwd, "hy3.db")

    assert _run(["init", "--db", db], cwd).returncode == 0

    new = _run(["session", "new", "--db", db, "phase0 smoke goal"], cwd)
    assert new.returncode == 0
    sid = new.stdout.strip()
    assert sid  # ULID printed

    # The command that previously crashed with AttributeError on args.limit.
    listing = _run(["session", "list", "--db", db], cwd)
    assert listing.returncode == 0
    assert sid in listing.stdout

    assert _run(["session", "show", "--db", db, sid], cwd).returncode == 0
    assert _run(["events", "tail", "--db", db], cwd).returncode == 0
    assert _run(["search", "--db", db, "phase0"], cwd).returncode == 0
