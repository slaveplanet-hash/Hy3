-- HY3 schema, migration 001 (plan §4).
--
-- Domain tables are reproduced exactly as specified in the build plan.
-- `schema_migrations` is migration INFRASTRUCTURE (required by store.py's
-- idempotent runner); it is not domain state, so it is intentionally not
-- part of the plan's data-model description.
--
-- `events_fts` is a contentless FTS5 table (content=''). Searchable text is
-- written with an explicit integer rowid equal to the owning event's rowid,
-- so a MATCH result joins back to `events WHERE rowid = ?`. Events are
-- append-only, so the FTS table never needs UPDATE/DELETE.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at INTEGER NOT NULL,
  name       TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  id           TEXT PRIMARY KEY,        -- ULID
  parent_id    TEXT REFERENCES sessions(id),
  title        TEXT,
  goal         TEXT NOT NULL,
  status       TEXT NOT NULL,           -- planning|running|paused|done|failed|aborted
  started_at   INTEGER NOT NULL,
  ended_at     INTEGER,
  cost_usd     REAL DEFAULT 0,
  tokens_in    INTEGER DEFAULT 0,
  tokens_out   INTEGER DEFAULT 0,
  tags         TEXT                     -- json array
);

CREATE TABLE IF NOT EXISTS runs (
  id          TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL REFERENCES sessions(id),
  dag_json    TEXT NOT NULL,
  budget_json TEXT NOT NULL,            -- max_steps, max_usd, wall_clock_s
  outcome     TEXT,                     -- success|partial|failed|aborted
  started_at  INTEGER NOT NULL,
  ended_at    INTEGER
);

CREATE TABLE IF NOT EXISTS jobs (
  id            TEXT PRIMARY KEY,
  run_id        TEXT NOT NULL REFERENCES runs(id),
  capability_id TEXT NOT NULL,
  profile       TEXT,
  depends_on    TEXT,                   -- json array of job ids
  status        TEXT NOT NULL,          -- pending|running|passed|failed|skipped
  attempt       INTEGER DEFAULT 0,
  risk          TEXT NOT NULL,
  started_at    INTEGER, ended_at INTEGER
);

-- the spine --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
  id           TEXT PRIMARY KEY,
  session_id   TEXT NOT NULL,
  run_id       TEXT,
  job_id       TEXT,
  ts           INTEGER NOT NULL,
  kind         TEXT NOT NULL,           -- see event kinds below
  capability_id TEXT,
  provider     TEXT,
  risk         TEXT,
  payload      TEXT NOT NULL,           -- json
  redacted     INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, ts);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
  body, content='', tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS artifacts (
  id         TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  job_id     TEXT,
  sha256     TEXT NOT NULL,
  path       TEXT NOT NULL,
  kind       TEXT NOT NULL,             -- scan|capture|screenshot|report|snapshot|code|log
  bytes      INTEGER,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_sha ON artifacts(sha256);

-- cross-referencing ------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
  id      TEXT PRIMARY KEY,
  kind    TEXT NOT NULL,                -- ip|mac|hostname|domain|port|process|pid|path|error|asn|device|model|project
  value   TEXT NOT NULL,
  norm    TEXT NOT NULL,                -- normalized form for matching
  first_seen INTEGER, last_seen INTEGER,
  UNIQUE(kind, norm)
);

CREATE TABLE IF NOT EXISTS mentions (
  entity_id TEXT NOT NULL REFERENCES entities(id),
  event_id  TEXT NOT NULL REFERENCES events(id),
  session_id TEXT NOT NULL,
  ts        INTEGER NOT NULL,
  PRIMARY KEY(entity_id, event_id)
);

CREATE TABLE IF NOT EXISTS edges (
  src_id TEXT NOT NULL,                 -- any of: session|event|artifact|entity|memory id
  dst_id TEXT NOT NULL,
  rel    TEXT NOT NULL,                 -- derived_from|supersedes|contradicts|same_entity|fixed_by|caused_by
  weight REAL DEFAULT 1.0,
  created_at INTEGER NOT NULL,
  PRIMARY KEY(src_id, dst_id, rel)
);

-- semantic tier ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS memories (
  id         TEXT PRIMARY KEY,
  session_id TEXT,
  kind       TEXT NOT NULL,             -- session_summary|finding|failure|fact|baseline
  text       TEXT NOT NULL,             -- <= ~200 tokens
  confidence REAL DEFAULT 0.6,
  superseded_by TEXT,
  created_at INTEGER NOT NULL
);
-- vector index via sqlite-vec on memories.text embedding (added in Phase 4)

-- procedural tier --------------------------------------------------------
CREATE TABLE IF NOT EXISTS skills (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  version      INTEGER NOT NULL,
  class        TEXT NOT NULL,           -- recorded|composed|generated
  schema_json  TEXT NOT NULL,
  impl_path    TEXT,
  risk         TEXT NOT NULL,
  status       TEXT NOT NULL,           -- proposed|sandboxed|approved|active|deprecated
  approved_by  TEXT,
  success_n    INTEGER DEFAULT 0,
  fail_n       INTEGER DEFAULT 0,
  last_used    INTEGER,
  deprecated_by TEXT,
  UNIQUE(name, version)
);
