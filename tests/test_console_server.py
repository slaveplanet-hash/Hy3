"""Integration test: the stdlib HTTP server serves the static UI and the API.

Spins up a real socket on an ephemeral port, then drives it with urllib so we
exercise the full request path (routing, JSON encoding, static file serving).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from hy3.console.server import make_server

from console_seed import seed_store


def _wait_get(url, tries: int = 80):
    last = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(url, timeout=2)
        except urllib.error.URLError as exc:
            last = exc
            time.sleep(0.05)
    raise last


def test_server_serves_static_and_api():
    path = seed_store()
    try:
        httpd, store = make_server(path, host="127.0.0.1", port=0)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        base = f"http://127.0.0.1:{port}"
        try:
            # Index HTML
            r = _wait_get(base + "/")
            assert r.status == 200
            assert "text/html" in r.headers.get("Content-Type", "")
            assert "event-list" in r.read().decode()

            # Static JS + CSS
            r = _wait_get(base + "/static/app.js")
            assert r.status == 200
            assert "javascript" in r.headers.get("Content-Type", "")
            r = _wait_get(base + "/static/styles.css")
            assert r.status == 200
            assert "text/css" in r.headers.get("Content-Type", "")

            # API: sessions
            r = _wait_get(base + "/api/sessions")
            data = json.loads(r.read())
            assert isinstance(data, list) and len(data) == 2

            # API: filtered events (sess_a is seeded with events)
            sid = "sess_a"
            qs = urllib.parse.urlencode({"filter": "kind:cap.call"})
            r = _wait_get(f"{base}/api/sessions/{sid}/events?{qs}")
            d = json.loads(r.read())
            assert d["count"] >= 1

            # API: single event (job context)
            eid = d["events"][0]["id"]
            r = _wait_get(f"{base}/api/events/{eid}")
            ev = json.loads(r.read())
            assert ev["job"] is not None

            # API: 404 for unknown event (urllib raises HTTPError on 4xx)
            try:
                _wait_get(f"{base}/api/events/does-not-exist")
                raise AssertionError("expected 404 for unknown event")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
        finally:
            httpd.shutdown()
            httpd.server_close()
            store.close()
    finally:
        import os
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
