"""Stdlib HTTP server for the operator console (plan §6/§16).

Zero external dependencies: a thin ``http.server`` wrapper routes ``/api/*`` to
:class:`ConsoleApi` and serves the static console UI from ``static/``. The server
is fully local (binds 127.0.0.1 by default) and read-only — it never mutates the
store. ``make_server`` is the single entry point used by the CLI.
"""
from __future__ import annotations

import http.server
import json
import os
import threading
import urllib.parse
from typing import Tuple

from hy3.core.store import Store

from .api import ConsoleApi

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIGRATIONS_DIR = os.path.join(REPO_ROOT, "migrations")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_ALLOWED_STATIC = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
}


class _Handler(http.server.BaseHTTPRequestHandler):
    """Per-request handler; ``api`` is injected by the factory in ``make_server``."""

    api: ConsoleApi

    def _send_json(self, obj: object, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, name: str) -> None:
        ctype = _ALLOWED_STATIC.get(name)
        if ctype is None:
            self._not_found()
            return
        path = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(path):
            self._not_found()
            return
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self) -> None:
        self._send_json({"error": "not found"}, status=404)

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        try:
            if route in ("/", "/index.html"):
                self._serve_static("index.html")
                return
            if route.startswith("/static/"):
                self._serve_static(os.path.basename(route[len("/static/"):]))
                return
            if route.startswith("/api/"):
                self._serve_api(route, parsed)
                return
            self._not_found()
        except Exception as exc:  # never leak a stack trace to the browser
            self._send_json({"error": str(exc)}, status=500)

    def _serve_api(self, route: str, parsed: urllib.parse.ParseResults) -> None:
        qs = urllib.parse.parse_qs(parsed.query)
        api = self.api

        def one(name: str, default: str | None = None) -> str | None:
            v = qs.get(name)
            return v[0] if v else default

        def i(name: str, default: int) -> int:
            try:
                return int(one(name, str(default)))
            except (TypeError, ValueError):
                return default

        if route == "/api/sessions":
            self._send_json(api.sessions(limit=i("limit", 100)))
            return
        if route.startswith("/api/sessions/"):
            sid = route[len("/api/sessions/"):]
            if sid.endswith("/events"):
                fid = sid[: -len("/events")]
                data = api.events(
                    fid,
                    filter=one("filter", "") or "",
                    limit=i("limit", 500),
                    query=one("q"),
                )
                self._send_json(data)
                return
            sess = api.session_detail(sid)
            self._send_json(sess if sess is not None else {"error": "not found"}, 200 if sess else 404)
            return
        if route.startswith("/api/events/"):
            eid = route[len("/api/events/"):]
            ev = api.event(eid)
            self._send_json(ev if ev is not None else {"error": "not found"}, 200 if ev else 404)
            return
        if route.startswith("/api/runs"):
            if route.endswith("/jobs"):
                rid = route[len("/api/runs/"): -len("/jobs")]
                self._send_json(api.jobs(rid))
                return
            self._send_json(api.runs(session_id=one("session")))
            return
        if route.startswith("/api/artifacts"):
            sid = one("session")
            if not sid:
                self._send_json({"error": "session query param required"}, status=400)
                return
            self._send_json(api.artifacts(session_id=sid))
            return
        if route == "/api/caps":
            self._send_json(api.caps())
            return
        self._not_found()

    def log_message(self, *args) -> None:  # silence default stderr logging
        pass


def _make_handler(api: ConsoleApi):
    """Build a handler class bound to a specific ``ConsoleApi`` instance."""

    class _Bound(_Handler):
        pass

    _Bound.api = api
    return _Bound


def make_server(
    db_path: str, host: str = "127.0.0.1", port: int = 8080
) -> Tuple[http.server.HTTPServer, Store]:
    """Open the store (applying migrations) and return a configured HTTP server."""
    store = Store(db_path, check_same_thread=False)
    store.migrate(MIGRATIONS_DIR)
    api = ConsoleApi(store)
    httpd = http.server.HTTPServer((host, port), _make_handler(api))
    return httpd, store


def serve_forever(db_path: str, host: str = "127.0.0.1", port: int = 8080) -> None:
    """Blocking helper used by the CLI: serve until interrupted."""
    httpd, _ = make_server(db_path, host=host, port=port)
    url = f"http://{host}:{port}"
    # Print on the real stdout so the operator sees the URL immediately.
    print(f"HY3 operator console: {url}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()


__all__ = ["make_server", "serve_forever"]
