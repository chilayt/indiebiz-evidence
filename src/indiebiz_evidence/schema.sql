-- indiebiz-evidence (core) schema.
-- Generic engine only: any periodic snapshot source lands in generic_facts.
-- Vertical-specific tables, if any, live in a separate private layer, not in this package.
PRAGMA user_version = 4;

-- Anomaly rows. slug is '<source>:<entity>' for generic sources; the source-level
-- pseudo entity is '<source>:__schema__'.
CREATE TABLE IF NOT EXISTS anomalies(
  observed_date TEXT NOT NULL,
  slug          TEXT NOT NULL,
  kind          TEXT NOT NULL,
  severity      TEXT,
  detail        TEXT,
  PRIMARY KEY(observed_date, slug, kind)
);

-- Every file the importer looked at, and what happened to it.
CREATE TABLE IF NOT EXISTS ingest_files(
  path          TEXT PRIMARY KEY,
  observed_date TEXT,
  slug          TEXT,
  status        TEXT,
  message       TEXT
);

-- Registered generic sources.
CREATE TABLE IF NOT EXISTS sources(
  source        TEXT PRIMARY KEY,
  config        TEXT,
  first_seen    TEXT,
  last_seen     TEXT,
  entity_count  INTEGER,
  field_count   INTEGER
);

-- Narrow fact table: one row per (date, source, entity, field).
-- num is the parsed number (NULL when the value is not numeric); text is always
-- the original string, so a parsed value can always be checked against its source
-- (discipline 5). Absent fields get NO row -- missing is not zero.
CREATE TABLE IF NOT EXISTS generic_facts(
  observed_date TEXT NOT NULL,
  source        TEXT NOT NULL,
  entity        TEXT NOT NULL,
  field         TEXT NOT NULL,
  num           REAL,
  text          TEXT,
  raw_ref       TEXT,
  PRIMARY KEY(observed_date, source, entity, field)
);

CREATE INDEX IF NOT EXISTS idx_anomalies_kind ON anomalies(kind);
CREATE INDEX IF NOT EXISTS idx_gf_series ON generic_facts(source, entity, field, observed_date);
CREATE INDEX IF NOT EXISTS idx_gf_date ON generic_facts(source, observed_date);

-- One row per (source, capture date) the importer actually ran, including batches
-- that yielded no usable facts. Without this the timeline could only be read from
-- generic_facts, so a failed capture vanished and the previous day looked "latest".
CREATE TABLE IF NOT EXISTS capture_batches(
  source        TEXT NOT NULL,
  observed_date TEXT NOT NULL,
  files         INTEGER,
  facts         INTEGER,
  PRIMARY KEY(source, observed_date)
);

CREATE INDEX IF NOT EXISTS idx_batches_source ON capture_batches(source, observed_date);

-- Confirmed cross-source entity alignments. A human decides that (source, entity)
-- refers to canonical_id; the tool never auto-links. propose_entity_links only
-- offers candidates with field-value evidence; confirm_entity_link records the
-- human decision here. cross_check(canonical_id=...) then compares every mapped
-- (source, entity) together. This turns manual alignment from "redo every time"
-- into "decide once, store it" -- the decision stays a human's, not a verdict.
CREATE TABLE IF NOT EXISTS entity_links(
  source        TEXT NOT NULL,
  entity        TEXT NOT NULL,
  canonical_id  TEXT NOT NULL,
  decided_by    TEXT,
  decided_at    TEXT,
  evidence      TEXT,
  PRIMARY KEY(source, entity)
);

CREATE INDEX IF NOT EXISTS idx_links_canonical ON entity_links(canonical_id);
