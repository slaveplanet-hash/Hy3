#!/usr/bin/env python3
"""HY3 command-line interface.

Usage:
    hy3 init
    hy3 session new "<goal>"
    hy3 session list
    hy3 session show <id>
    hy3 session resume <id>
    hy3 events tail [--session <id>] [--kind <k>] [--limit N]
    hy3 search "<query>"
    hy3 caps list
    hy3 caps show <id>
    hy3 caps route "<goal>" [--top-k N]

The database defaults to ./hy3.db in the current directory; migrations live in
../migrations relative to this script. `hy3 caps` is database-independent.
"""
from __future__ import annotations

import argparse
import datetime
import json
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
from hy3.registry import Registry  # noqa: E402
from hy3.registry.capability import Risk  # noqa: E402
from hy3.orchestrator import Boss  # noqa: E402
from hy3.orchestrator.dag import DagError  # noqa: E402

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


def cmd_caps_list(args: argparse.Namespace) -> int:
    """List every registered capability under one schema."""
    reg = Registry.load()
    rows = reg.all()
    if not rows:
        print("(no capabilities)")
        return 0
    for c in rows:
        print(
            f"{c.id:24} {c.kind.value:10} {c.risk.value:11} "
            f"{c.provenance:14} {c.summary}"
        )
    print(f"-- {len(rows)} capabilities")
    return 0


def cmd_caps_show(args: argparse.Namespace) -> int:
    """Show one capability's full schema and metadata."""
    reg = Registry.load()
    c = reg.get(args.id)
    if c is None:
        print(f"unknown capability: {args.id}", file=sys.stderr)
        return 2
    print(f"id:         {c.id}")
    print(f"kind:       {c.kind.value}")
    print(f"risk:       {c.risk.value}")
    print(f"provenance: {c.provenance}")
    print(f"summary:    {c.summary}")
    print(f"requires:   {', '.join(c.requires) or '-'}")
    print(f"tags:       {', '.join(c.tags) or '-'}")
    print(
        f"cost:       vram={c.cost.vram_gb}gb "
        f"usd={c.cost.usd_per_call} p50={c.cost.p50_latency_ms}ms"
    )
    print(f"schema_in:  {json.dumps(c.schema_in)}")
    print(f"schema_out: {json.dumps(c.schema_out)}")
    return 0


def cmd_caps_route(args: argparse.Namespace) -> int:
    """Two-stage route a goal and print the capability set the planner would see."""
    reg = Registry.load()
    caps = reg.retrieve(args.goal, top_k=args.top_k)
    pinned = {"plan.replan", "memory.search", "report.write"}
    for c in caps:
        mark = " [pinned]" if c.id in pinned else ""
        print(
            f"{c.id:24} {c.kind.value:10} {c.risk.value:11}{mark}  {c.summary}"
        )
    print(f"-- {len(caps)} capabilities routed for: {args.goal}")
    return 0


def cmd_plan_validate(args: argparse.Namespace) -> int:
    """Validate a boss plan file: check caps exist, risk ceiling, acyclicity, and
    print the topological order and profile batches the scheduler would execute."""
    reg = Registry.load()
    try:
        with open(args.path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read plan file: {exc}", file=sys.stderr)
        return 2
    specs = doc["jobs"] if isinstance(doc, dict) and "jobs" in doc else doc
    ceiling = doc.get("session_ceiling", "privileged") if isinstance(doc, dict) else "privileged"
    max_jobs = doc.get("max_jobs", 12) if isinstance(doc, dict) else 12
    try:
        dag = Boss().plan_from_spec(
            specs, registry=reg, session_ceiling=Risk(ceiling), max_jobs=max_jobs
        )
    except DagError as exc:
        print(f"INVALID PLAN: {exc}", file=sys.stderr)
        return 1
    print(f"VALID PLAN: {len(dag.jobs)} jobs, session ceiling {dag.session_ceiling.value}")
    print("topological order:")
    for jid in dag.topo_order():
        print(f"  {jid}")
    print("profile batches (one model load each):")
    for profile, batch in dag.batches():
        print(f"  [{profile}] " + " ".join(j.id for j in batch))
    print(f"-- {len(dag.batches())} batch(es) => <= {len(dag.batches())} model load(s)")
    return 0


def cmd_console(args: argparse.Namespace) -> int:
    """Launch the operator console (local web UI) over the store."""
    from hy3.console.server import serve_forever

    serve_forever(args.db, host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the hy3 CLI."""
    # Shared so --db works before OR after the subcommand.
    db_parent = argparse.ArgumentParser(add_help=False)
    db_parent.add_argument(
        "--db", default=DEFAULT_DB,
        help="path to hy3.db (default: ./hy3.db in the current directory)",
    )
    p = argparse.ArgumentParser(prog="hy3", description="HY3 Phase 0 CLI", parents=[db_parent])
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", parents=[db_parent], help="initialize the local database")

    sp = sub.add_parser("session", parents=[db_parent], help="session commands")
    sp_sub = sp.add_subparsers(dest="session_cmd", required=True)
    p_new = sp_sub.add_parser("new", parents=[db_parent], help="create a new session")
    p_new.add_argument("goal")
    p_new.add_argument("--title")
    p_new.add_argument("--tags", help="comma-separated tags")
    p_list = sp_sub.add_parser("list", parents=[db_parent], help="list sessions")
    p_list.add_argument("--limit", type=int, default=20)
    p_show = sp_sub.add_parser("show", parents=[db_parent], help="show a session")
    p_show.add_argument("id")
    p_show.add_argument("--limit", type=int, default=20)
    p_res = sp_sub.add_parser("resume", parents=[db_parent], help="resume a session")
    p_res.add_argument("id")

    et = sub.add_parser("events", parents=[db_parent], help="event commands")
    et_sub = et.add_subparsers(dest="events_cmd", required=True)
    et_tail = et_sub.add_parser("tail", parents=[db_parent], help="tail recent events")
    et_tail.add_argument("--session")
    et_tail.add_argument("--kind")
    et_tail.add_argument("--limit", type=int, default=20)

    s = sub.add_parser("search", parents=[db_parent], help="full-text search events")
    s.add_argument("query")
    s.add_argument("--session")
    s.add_argument("--limit", type=int, default=50)

    caps = sub.add_parser("caps", parents=[db_parent], help="capability registry commands")
    caps_sub = caps.add_subparsers(dest="caps_cmd", required=True)
    caps_sub.add_parser("list", parents=[db_parent], help="list all capabilities")
    caps_show = caps_sub.add_parser("show", parents=[db_parent], help="show one capability")
    caps_show.add_argument("id")
    caps_route = caps_sub.add_parser("route", parents=[db_parent], help="two-stage route a goal")
    caps_route.add_argument("goal")
    caps_route.add_argument("--top-k", type=int, default=15, dest="top_k")

    plan = sub.add_parser("plan", parents=[db_parent], help="orchestrator plan commands")
    plan_sub = plan.add_subparsers(dest="plan_cmd", required=True)
    plan_val = plan_sub.add_parser("validate", parents=[db_parent], help="validate a plan JSON file")
    plan_val.add_argument("path", help="path to plan JSON (a job list or {\"jobs\": [...])")

    console = sub.add_parser(
        "console", parents=[db_parent], help="launch the operator console (web UI)"
    )
    console.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    console.add_argument("--port", type=int, default=8080, help="bind port (default 8080)")
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
    "caps": {
        "list": cmd_caps_list,
        "show": cmd_caps_show,
        "route": cmd_caps_route,
    },
    "plan": {
        "validate": cmd_plan_validate,
    },
    "console": cmd_console,
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
    if args.cmd == "caps":
        return DISPATCH["caps"][args.caps_cmd](args)
    if args.cmd == "plan":
        return DISPATCH["plan"][args.plan_cmd](args)
    if args.cmd == "console":
        return DISPATCH["console"](args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
