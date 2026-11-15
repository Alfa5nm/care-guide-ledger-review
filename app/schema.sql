CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    suffix TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','processing','completed','failed')),
    progress INTEGER NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT 'Queued',
    attempt INTEGER NOT NULL DEFAULT 0,
    lease_until REAL,
    lease_token TEXT,
    created_at REAL NOT NULL,
    processing_ms INTEGER,
    error TEXT,
    body TEXT,
    warnings TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS jobs_by_status ON documents(status, created_at);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    data TEXT NOT NULL,
    evidence TEXT NOT NULL,
    duplicate_key TEXT,
    issues TEXT NOT NULL,
    UNIQUE(document_id, position)
);
CREATE INDEX IF NOT EXISTS invoice_document ON invoices(document_id);
CREATE INDEX IF NOT EXISTS invoice_duplicate ON invoices(duplicate_key);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    happened_at REAL NOT NULL,
    event TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS history_document ON history(document_id, id);
CREATE VIRTUAL TABLE IF NOT EXISTS document_search USING fts5(document_id UNINDEXED, body);
CREATE TABLE IF NOT EXISTS search_vectors (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    vector TEXT NOT NULL
);
