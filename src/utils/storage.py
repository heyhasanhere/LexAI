import json
import uuid
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

CREATE_TABLES_SQL = """
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
    pattern_id       TEXT PRIMARY KEY,
    document_type    TEXT,
    section          TEXT NOT NULL,
    edit_type        TEXT NOT NULL,
    trigger          TEXT NOT NULL,
    original_text    TEXT NOT NULL,
    corrected_text   TEXT NOT NULL,
    frequency        INTEGER NOT NULL DEFAULT 1,
    first_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_draft_ids TEXT[]
);

CREATE INDEX IF NOT EXISTS idx_edit_patterns_lookup
    ON edit_patterns (document_type, section, edit_type);
"""


def _connect(dsn: str) -> psycopg2.extensions.connection:
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    return conn


def init_db(dsn: str) -> None:
    with _connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLES_SQL)


# ── Documents ──────────────────────────────────────────────────────────────────

def create_document(filename: str, file_type: str, dsn: str) -> str:
    document_id = f"doc-{uuid.uuid4().hex[:8]}"
    with _connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO documents (document_id, filename, file_type) VALUES (%s, %s, %s)",
                (document_id, filename, file_type),
            )
    return document_id


def update_document(
    document_id: str,
    status: str,
    dsn: str,
    page_count: int | None = None,
    fields_json: dict | None = None,
    flags: list[str] | None = None,
    error_detail: str | None = None,
) -> None:
    with _connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents SET
                    status = %s,
                    page_count = COALESCE(%s, page_count),
                    fields_json = COALESCE(%s, fields_json),
                    flags = COALESCE(%s, flags),
                    error_detail = COALESCE(%s, error_detail)
                WHERE document_id = %s
                """,
                (
                    status,
                    page_count,
                    json.dumps(fields_json) if fields_json else None,
                    flags,
                    error_detail,
                    document_id,
                ),
            )


def get_document(document_id: str, dsn: str) -> dict | None:
    with _connect(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM documents WHERE document_id = %s", (document_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def delete_document(document_id: str, dsn: str) -> bool:
    with _connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM drafts WHERE %s = ANY(document_ids)", (document_id,))
            cur.execute("DELETE FROM documents WHERE document_id = %s", (document_id,))
            return cur.rowcount > 0


def list_documents(dsn: str, status: str | None = None, limit: int = 20, offset: int = 0) -> tuple[int, list[dict]]:
    with _connect(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where = "WHERE status = %s" if status else ""
            params = [status] if status else []
            cur.execute(f"SELECT COUNT(*) FROM documents {where}", params)
            total = cur.fetchone()["count"]
            cur.execute(
                f"SELECT * FROM documents {where} ORDER BY upload_timestamp DESC LIMIT %s OFFSET %s",
                params + [limit, offset],
            )
            return total, [dict(r) for r in cur.fetchall()]


# ── Drafts ─────────────────────────────────────────────────────────────────────

def create_draft(
    document_ids: list[str],
    draft_type: str,
    original_text: str,
    ungrounded_sentences: list[str],
    citations: list[dict],
    patterns_used: list[str],
    dsn: str,
) -> str:
    draft_id = f"draft-{uuid.uuid4().hex[:8]}"
    with _connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO drafts
                    (draft_id, document_ids, draft_type, original_text,
                     ungrounded_sentences, citations_json, patterns_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    draft_id,
                    document_ids,
                    draft_type,
                    original_text,
                    ungrounded_sentences,
                    json.dumps(citations),
                    patterns_used,
                ),
            )
    return draft_id


def get_draft(draft_id: str, dsn: str) -> dict | None:
    with _connect(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM drafts WHERE draft_id = %s", (draft_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def submit_draft(draft_id: str, submitted_text: str, dsn: str) -> None:
    with _connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE drafts SET status = 'submitted', submitted_text = %s WHERE draft_id = %s",
                (submitted_text, draft_id),
            )


def list_drafts(dsn: str, status: str | None = None, limit: int = 20, offset: int = 0) -> tuple[int, list[dict]]:
    with _connect(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where = "WHERE status = %s" if status else ""
            params = [status] if status else []
            cur.execute(f"SELECT COUNT(*) FROM drafts {where}", params)
            total = cur.fetchone()["count"]
            cur.execute(
                f"SELECT * FROM drafts {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params + [limit, offset],
            )
            return total, [dict(r) for r in cur.fetchall()]
