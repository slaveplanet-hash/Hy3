# Phase 6 — Operator Console (v0.5.0)

Local-first, dependency-free observability UI for the HY3 harness. It renders a
Wireshark-style master/detail view over the store that Phase 0-3 already populate,
so operators can audit exactly what the harness did, filter it like a packet
capture, and drill into any job's spec / inputs / result / acceptance.

## What shipped

- **Backend API** (`hy3/console/api.py`) — `ConsoleApi`, a stateless read surface
  over a `Store`: sessions, session detail (event count + cost aggregate), the
  flat event list (with the display-filter), single-event detail with job context
  (spec / acceptance / call-inputs / result / inline diff), runs + jobs, artifacts,
  and the capability registry for labeling. Every method returns plain dicts, so
  the HTTP layer and the tests share one code path.
- **Display-filter** (`hy3/console/filter.py`) — Wireshark-style grammar:
  `kind:cap.call`, `risk:write`, `capability:net.scan` (alias `cap`),
  `provider:lm-studio`, `session:`, `job:`, `entity:192.168.1.180` (payload
  substring), `text:"dns query"` (alias `body`), and free terms. Supports comma
  lists (`kind:cap.call,cap.result` → `IN`), negation (`!kind:cap.error` or
  `kind!=cap.error`), quoted values, and unknown keys surface as filter errors to
  the UI. Compiles to **parameterized** SQL only (injection-safe by construction);
  negation wraps in parentheses for correct `AND`/`OR` precedence.
- **HTTP server** (`hy3/console/server.py`) — stdlib `http.server`, zero external
  deps. Routes `/api/*` → `ConsoleApi`, `/static/*` + `/` → the UI. Bind 127.0.0.1
  by default; read-only (never mutates the store). `make_server()` is the single
  entry point used by the CLI.
- **Frontend** (`hy3/console/static/{index.html,styles.css,app.js}`) — vanilla ES
  modules, no build step, fully offline. Professional dark "operator console"
  theme with design tokens. Layout: session-history ribbon → display-filter bar
  (live parse + error chips) → flat sortable event list (colored kind/risk badges,
  **hatched** failed segments: `cap.error` / `accept.fail` / `gate.denied`;
  **pulsing** gated segments: `gate.*`) → selection-linked detail panes (event
  payload + job spec / inputs / result / acceptance / diff). Keyboard-navigable
  (Arrow/Home/End/Enter), ARIA roles, focus-visible outlines, reduced-motion aware.
- **CLI** (`bin/hy3.py`) — `hy3 console [--db DB] [--host HOST] [--port PORT]`.

## Stack decision

Built with a stdlib HTTP server + vanilla JS rather than React/Vite. Rationale:
HY3's principle is local-first and minimal-dependency, and dragging a Node build
pipeline into the Python venv would contradict that. The FrontendDeveloper quality
bar (accessibility, keyboard nav, design tokens, focus states) is honored in plain
CSS/JS. If React is wanted later, the API is framework-agnostic and stable.

## Tests

- `tests/test_console_filter.py` — parser + compiler (equality, comma-IN, negation
  both forms, column/entity/text keys, free text, LIKE-wildcard escaping, unknown
  key errors, session scoping, quoted values).
- `tests/test_console_api.py` — full API over a seeded store (filters, job context
  spec/acceptance/diff, runs/jobs, artifacts, caps).
- `tests/test_console_server.py` — integration: real socket serves `/`, static
  assets, and the API (including 404 handling).
- `tests/console_seed.py` — shared temp store with realistic Phase 0-3 data.

**120 tests pass** (94 prior + 26 console). `node --check` validates `app.js`.

## Notes / follow-ups

- The carried plan markdown (`HY3_HARNESS_PLAN.md`) was not present on disk, so the
  console was built from the Phase 6 description in the conversation summary
  (§6/§16 Wireshark master-detail vocabulary). If the original spec differed, the
  detail panes / filter keys are easy to extend.
- Phases 4-5 (memory tiers; NetScope read tier + 8 playbooks) remain deferred.
- `entity:` filtering currently matches the event payload (substring); when Phase 4
  populates the `entities`/`mentions` tables, the same key can also join via
  `mentions` for precise entity resolution.
- GitHub connector is currently disconnected; the user pushes `v0.5.0` from their
  own terminal after this commit.
