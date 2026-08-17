"""Phase 6 — operator console (plan §6/§16).

A local-first, dependency-free observability UI for the harness: a stdlib HTTP
server exposes a read-only JSON API over the store, and a vanilla-JS frontend
renders a Wireshark-style master-detail view (session ribbon, display-filterable
event list, selection-linked detail panes for job spec / payload / acceptance /
diff). No external packages and no build step are required.
"""
from __future__ import annotations

from .api import ConsoleApi
from .filter import compile_event_filter, parse_filter
from .server import make_server, serve_forever

__all__ = ["ConsoleApi", "parse_filter", "compile_event_filter", "make_server", "serve_forever"]
