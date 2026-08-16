#!/usr/bin/env python3
"""HY3 Phase 0 command-line interface.

Usage:
    hy3 init
    hy3 session new "<goal>"
    hy3 session list
    hy3 session show <id>
    hy3 session resume <id>
    hy3 events tail [--session <id>] [--kind <k>] [--limit N]
    hy3 search "<query>"

The database defaults to ./hy3.db in the current directory; migrations live in
../migrations relative to this script.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from typing import Optional

# Make the hy3 package importable when run as bin/hy3.py.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from hy3.core import events as events_mod  # noqa: E402
from hy3.core import session as session_mod  # noqa: E402
from hy3.core.store import Store  # noqa: E402

MIGRATIONS_DIR = os.path.join(REPO_ROOT, "migrations")
DEFAULT_DB = os.path.join(os.getcwd(), "hy3.db")


def _fmt_ts(ms: Optional[int]) -> str:
    """Format integer epoch-millis as a UTC timestamp string, or '-' if None."""
    if ms is None:
        return "-"
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc).isoformat()


def _store(db_path: str) -> Store:
    """Open the store at ``db_path`` and ensure migrations are applied."""
    store = Store(db_path)
    store.migrate(MIGRATIONS_DIR)
    return store


def cmd_init(args: argparse.Namespace) -> int:
    """Create/initialize the local database (idempotent)."""
    store = _store(args.db)
    store.checkpoint()
    print(f"initialized: {store.path}")
    return 0


def cmd_session_new(args: argparse.Namespace) -> int:
    """Create a new session and print its id."""
    store = _store(args.db)
    tags = args.tags.split(",") if args.tags else None
    sess = session_mod.create(store, args.goal, tags=tags, title=args.title)
    print(sess.id)
    return 0


def cmd_session_list(args: argparse.Namespace) -> int:
    """List sessions, newest first."""
    store = _store(args.db)
    rows = store.list_sessions(limit=args.limit)
    if not rows:
        print("(no sessions)")
        return 0
    for r in rows:
        print(f"{r['id']}  {r['status']:8}  {_fmt_ts(r['started_at'])}  {r['goal']}")
    return 0


def cmd_session_show(args: argparse.Namespace) -> int:
    """Show one session's details, cost, and recent events."""
    store = _store(args.db)
    sess, last_job = session_mod.resume(store, args.id)
    print(f"id:         {sess.id}")
    print(f"goal:       {sess.goal}")
    print(f"status:     {sess.status}")
    print(f"parent:     {sess.parent_id or '-'}")
    print(f"started:    {_fmt_ts(sess.started_at)}")
    print(f"ended:      {_fmt_ts(sess.ended_at)}")
    print(f"cost_usd:   {sess.cost_usd:.4f}")
    print(f"tokens:     in={sess.tokens_in} out={sess.tokens_out}")
    print(f"last job:   {last_job or '-'}")
    events = store.list_events(session_id=sess.id, limit=args.limit)
    print(f"events:     {len(events)} (showing last {min(args.limit, len(events))})")
    for ev in events[-args.limit:]:
        _print_event(ev)
    arts = store.list_artifacts(sess.id)
    if arts:
        print(f"artifacts:  {len(arts)}")
        for a in arts:
            print(f"  - {a['id']}  {a['kind']}  {a['sha256'][:12]}  {a['bytes']}B")
    return 0


def cmd_session_resume(args: argparse.Namespace) -> int:
    """Replay a session's events and report reconstructed state."""
    store = _store(args.db)
    sess, last_job = session_mod.resume(store, args.id)
    print(f"resumed:    {sess.id}")
    print(f"goal:       {sess.goal}")
    print(f"status:     {sess.status}")
    print(f"events:     {len(store.list_events(session_id=sess.id, limit=1_000_000))}")
    print(f"last job:   {last_job or '-'}")
    return 0


def cmd_events_tail(args: argparse.Namespace) -> int:
    """Print the most recent events (optionally filtered by session/kind)."""
    store = _store(args.db)
    rows = store.list_events(session_id=args.session, kind=args.kind, limit=args.limit)
    # list_events returns oldest-first; tail means newest-first.
    for ev in reversed(rows):
        _print_event(ev)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Full-text search over event payloads."""
    store = _store(args.db)
    rows = store.search_events(args.query, session_id=args.session, limit=args.limit)
    if not rows:
        print("(no matches)")
        return 0
    for ev in rows:
        _print_event(ev)
    print(f"-- {len(rows)} match(es)")
    return 0


def _print_event(ev) -> None:
    """Print one event row compactly."""
    kind = ev["kind"]
    cap = ev["capability_id"] or ""
    try:
        payload = ev["payload"]
        if len(payload) > 120:
            payload = payload[:117] + "..."
    except Exception:
        payload = ""
    print(f"  {_fmt_ts(ev['ts'])}  {kind:14} {cap:16} {payload}")


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the hy3 CLI."""
    p = argparse.ArgumentParser(prog="hy3", description="HY3 Phase 0 CLI")
    p.add_argument("--db", default=DEFAULT_DB, help="path to hy3.db (default: ./hy3.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="initialize the local database")

    sp = sub.add_parser("session", help="session commands")
    sp_sub = sp.add_subparsers(dest="session_cmd", required=True)
    p_new = sp_sub.add_parser("new", help="create a new session")
    p_new.add_argument("goal")
    p_new.add_argument("--title")
    p_new.add_argument("--tags", help="comma-separated tags")
    sp_sub.add_parser("list", help="list sessions")
    p_show = sp_sub.add_parser("show", help="show a session")
    p_show.add_argument("id")
    p_show.add_argument("--limit", type=int, default=20)
    p_res = sp_sub.add_parser("resume", help="resume a session")
    p_res.add_argument("id")

    et = sub.add_parser("events", help="event commands")
    et_sub = et.add_subparsers(dest="events_cmd", required=True)
    et_tail = et_sub.add_parser("tail", help="tail recent events")
    et_tail.add_argument("--session")
    et_tail.add_argument("--kind")
    et_tail.add_argument("--limit", type=int, default=20)

    s = sub.add_parser("search", help="full-text search events")
    s.add_argument("query")
    s.add_argument("--session")
    s.add_argument("--limit", type=int, default=50)
    return p


DISPATCH = {
    "init": cmd_init,
    "session": {
        "new": cmd_session_new,
        "list": cmd_session_list,
        "show": cmd_session_show,
        "resume": cmd_session_resume,
    },
    "events": {"tail": cmd_events_tail},
    "search": cmd_search,
}


def main(argv: Optional[list[str]] = None) -> int:
    """Parse arguments and dispatch to the matching command handler."""
    args = build_parser().parse_args(argv)
    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "session":
        return DISPATCH["session"][args.session_cmd](args)
    if args.cmd == "events":
        return DISPATCH["events"][args.events_cmd](args)
    if args.cmd == "search":
        return cmd_search(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
