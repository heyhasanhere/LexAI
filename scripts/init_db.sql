-- Runs automatically when the Postgres container starts (docker-compose mounts this file).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    document_id      TEXT PRIMARY KEY,
    filename         TEXT NOT NULL,
    file_type        TEXT NOT NULL,
    upload_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status           TEXT NOT NULL DEFAULT 'pending',
    page_count       INTEGER,
    fields_json      JSONB,
    flags            TEXT[],
    error_detail     TEXT
);

CREATE TABLE IF NOT EXISTS drafts (
    draft_id             TEXT PRIMARY KEY,
    document_ids         TEXT[] NOT NULL,
    draft_type           TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status               TEXT NOT NULL DEFAULT 'generated',
    original_text        TEXT NOT NULL,
    submitted_text       TEXT,
    ungrounded_sentences TEXT[],
    citations_json       JSONB,
    patterns_used        TEXT[]
);

CREATE TABLE IF NOT EXISTS edit_patterns (
    pattern_id      TEXT PRIMARY KEY,
    document_type   TEXT,
    section         TEXT NOT NULL,
    edit_type       TEXT NOT NULL,
    trigger         TEXT NOT NULL,
    original_text   TEXT NOT NULL,
    corrected_text  TEXT NOT NULL,
    frequency       INTEGER NOT NULL DEFAULT 1,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_draft_ids TEXT[]
);

CREATE INDEX IF NOT EXISTS idx_edit_patterns_lookup
    ON edit_patterns (document_type, section, edit_type);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id       TEXT PRIMARY KEY,
    document_id    TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_number    INTEGER NOT NULL,
    chunk_index    INTEGER NOT NULL,
    char_start     INTEGER NOT NULL,
    char_end       INTEGER NOT NULL,
    ocr_confidence FLOAT NOT NULL DEFAULT 1.0,
    token_count    INTEGER NOT NULL DEFAULT 0,
    text           TEXT NOT NULL,
    embedding      vector(1024)
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
