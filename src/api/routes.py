import os
import shutil
import tempfile
from pathlib import Path

import pytesseract
import yaml
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from src.api.schemas import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    DraftListResponse,
    DraftRequest,
    DraftResponse,
    ErrorResponse,
    ExtractedFieldsSchema,
    HealthResponse,
    PatternListResponse,
    PatternResponse,
    SubmitDraftRequest,
    SubmitDraftResponse,
)
from src.extraction.chunker import chunk_document
from src.extraction.field_extractor import extract_fields
from src.generation.draft_generator import generate_draft
from src.ingestion.loader import load_document
from src.learning.edit_tracker import classify_edits, diff_drafts
from src.learning.pattern_store import (
    delete_pattern,
    get_patterns,
    init_db as init_pattern_db,
    upsert_pattern,
)
from src.retrieval.vector_store import delete_by_document, query as vector_query, upsert_chunks
from src.utils.logger import get_logger
from src.utils.storage import (
    create_document,
    create_draft,
    delete_document,
    get_document,
    get_draft,
    init_db,
    list_documents,
    list_drafts,
    submit_draft,
    update_document,
)

logger = get_logger(__name__)

app = FastAPI(title="LexAI", version="0.1.0")

# ── Config — settings.yaml with LD_* env-var overrides ────────────────────────
# Any key in settings.yaml can be overridden at runtime with an env var using the
# prefix LD_ and double-underscore nesting:  LD_LLM__BASE_URL → llm.base_url
# This lets install.sh write a .env file without touching the YAML.

def _load_config() -> dict:
    path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
    try:
        cfg = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        cfg = {}

    for key, val in os.environ.items():
        if not key.startswith("LD_"):
            continue
        parts = key[3:].lower().split("__")
        node = cfg
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = val

    return cfg


_cfg = _load_config()

DSN = _cfg.get("storage", {}).get("postgres_dsn", "postgresql://ld:ld@localhost:5432/lexai")
CHROMA_HOST = _cfg.get("storage", {}).get("vector_store", {}).get("host", "localhost")
CHROMA_PORT = _cfg.get("storage", {}).get("vector_store", {}).get("port", 8001)
LLM_BASE_URL = _cfg.get("llm", {}).get("base_url", "http://localhost:8080/v1")
LLM_MODEL = _cfg.get("llm", {}).get("model", "Qwen/Qwen3-14B-AWQ")
LLM_API_KEY = _cfg.get("llm", {}).get("api_key", "local")
LLM_MAX_TOKENS = int(_cfg.get("llm", {}).get("max_tokens", 2000))
EMBED_DEVICE = _cfg.get("embedding", {}).get("device", "auto")
DOCUMENT_DIR = Path(_cfg.get("storage", {}).get("document_dir", "./data/documents"))
MAX_UPLOAD_BYTES = int(_cfg.get("server", {}).get("max_upload_size_mb", 50)) * 1024 * 1024

_RETRIEVAL_QUERIES: list[str] = (
    _cfg.get("retrieval", {}).get("queries_per_draft", {}).get("case_fact_summary")
    or [
        "parties entities people organizations and their roles",
        "dates deadlines amounts identifiers reference numbers",
        "clauses terms conditions obligations restrictions",
        "risks flags anomalies missing information gaps quality issues",
    ]
)


@app.on_event("startup")
def startup() -> None:
    DOCUMENT_DIR.mkdir(parents=True, exist_ok=True)
    init_db(DSN)
    init_pattern_db(DSN)
    logger.info("LexAI API started")


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    import chromadb
    vector_status = "connected"
    db_status = "connected"
    ocr_ok = True

    try:
        import psycopg2
        psycopg2.connect(DSN).close()
    except Exception:
        db_status = "unavailable"

    try:
        chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT).heartbeat()
    except Exception:
        vector_status = "unavailable"

    try:
        pytesseract.get_tesseract_version()
    except Exception:
        ocr_ok = False

    return HealthResponse(
        status="ok",
        vector_store=vector_status,
        database=db_status,
        ocr_available=ocr_ok,
    )


# ── Documents ──────────────────────────────────────────────────────────────────

@app.post("/documents", response_model=DocumentUploadResponse, status_code=202)
def upload_document(
    file: UploadFile = File(...),
    document_type_hint: str | None = Form(None),
) -> DocumentUploadResponse:
    document_id = create_document(file.filename, _file_type(file.filename), DSN)

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024*1024)} MB upload limit.",
            )
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        update_document(document_id, "processing", DSN)

        loaded = load_document(tmp_path)
        pages = [(p.page_number, p.text, p.ocr_confidence) for p in loaded.pages]
        flags = loaded.flags

        fields = extract_fields(
            loaded.page_annotated_text,
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
        )
        if document_type_hint and not fields.document_type:
            fields.document_type = document_type_hint

        chunks = chunk_document(document_id, pages)
        upsert_chunks(chunks, device=EMBED_DEVICE, host=CHROMA_HOST, port=CHROMA_PORT)

        dest = DOCUMENT_DIR / f"{document_id}{Path(file.filename).suffix}"
        shutil.move(str(tmp_path), dest)

        update_document(
            document_id,
            "ready",
            DSN,
            page_count=loaded.page_count,
            fields_json=fields.to_dict(),
            flags=flags + fields.flags,
        )

    except Exception as e:
        logger.error(f"Ingestion failed for {document_id}: {e}")
        update_document(document_id, "failed", DSN, error_detail=str(e))
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(e))

    return DocumentUploadResponse(
        document_id=document_id,
        filename=file.filename,
        status="ready",
    )


@app.get("/documents", response_model=DocumentListResponse)
def list_docs(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> DocumentListResponse:
    total, docs = list_documents(DSN, status=status, limit=limit, offset=offset)
    return DocumentListResponse(total=total, documents=[_doc_row_to_schema(d) for d in docs])


@app.get("/documents/{document_id}", response_model=DocumentResponse)
def get_doc(document_id: str) -> DocumentResponse:
    row = get_document(document_id, DSN)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return _doc_row_to_schema(row)


# ── Drafts ─────────────────────────────────────────────────────────────────────

@app.post("/drafts", response_model=DraftResponse, status_code=201)
def create_draft_endpoint(req: DraftRequest) -> DraftResponse:
    docs = [get_document(did, DSN) for did in req.document_ids]

    for doc, did in zip(docs, req.document_ids):
        if not doc:
            raise HTTPException(status_code=400, detail=f"Document {did} not found")
        if doc["status"] != "ready":
            raise HTTPException(status_code=400, detail=f"Document {did} status is '{doc['status']}'")

    import json
    from src.extraction.field_extractor import ExtractedFields
    fields_by_doc = {
        d["document_id"]: ExtractedFields(**(
            d["fields_json"] if isinstance(d["fields_json"], dict)
            else json.loads(d["fields_json"])
        )) if d.get("fields_json") else ExtractedFields()
        for d in docs
    }

    doc_type = next(
        (f.document_type for f in fields_by_doc.values() if f.document_type),
        None,
    )
    sections = ["parties", "key_dates", "key_clauses", "flags_and_risks", "obligation_tracker"]
    patterns = get_patterns(doc_type, sections, DSN)

    chunks = vector_query(
        queries=_RETRIEVAL_QUERIES,
        document_ids=req.document_ids,
        top_k=2,
        min_score=0.35,
        host=CHROMA_HOST,
        port=CHROMA_PORT,
        device=EMBED_DEVICE,
    )

    doc_meta = {
        d["document_id"]: {
            "filename": d.get("filename", ""),
            "page_count": d.get("page_count"),
            "upload_timestamp": d.get("upload_timestamp"),
        }
        for d in docs
    }

    try:
        result = generate_draft(
            document_ids=req.document_ids,
            fields_by_doc=fields_by_doc,
            chunks=chunks,
            patterns=patterns,
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
            max_tokens=LLM_MAX_TOKENS,
            doc_meta=doc_meta,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    from datetime import datetime, timezone
    draft_id = create_draft(
        document_ids=req.document_ids,
        draft_type=req.draft_type,
        original_text=result.text,
        ungrounded_sentences=result.ungrounded_sentences,
        citations=result.citations,
        patterns_used=result.patterns_used,
        dsn=DSN,
    )

    return DraftResponse(
        draft_id=draft_id,
        document_ids=req.document_ids,
        draft_type=req.draft_type,
        created_at=datetime.now(timezone.utc),
        status="generated",
        draft_text=result.text,
        ungrounded_sentences=result.ungrounded_sentences,
        citations=result.citations,
        patterns_used=result.patterns_used,
    )


@app.get("/drafts", response_model=DraftListResponse)
def list_drafts_endpoint(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> DraftListResponse:
    total, rows = list_drafts(DSN, status=status, limit=limit, offset=offset)
    return DraftListResponse(total=total, drafts=[_draft_row_to_schema(r) for r in rows])


@app.get("/drafts/{draft_id}", response_model=DraftResponse)
def get_draft_endpoint(draft_id: str) -> DraftResponse:
    row = get_draft(draft_id, DSN)
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _draft_row_to_schema(row)


@app.post("/drafts/{draft_id}/submit", response_model=SubmitDraftResponse)
def submit_draft_endpoint(draft_id: str, req: SubmitDraftRequest) -> SubmitDraftResponse:
    row = get_draft(draft_id, DSN)
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    if row["status"] == "submitted":
        raise HTTPException(status_code=400, detail="Draft already submitted")

    submit_draft(draft_id, req.submitted_text, DSN)

    doc_row = get_document(row["document_ids"][0], DSN)
    import json
    doc_type = None
    if doc_row and doc_row.get("fields_json"):
        raw = doc_row["fields_json"]
        fields = raw if isinstance(raw, dict) else json.loads(raw)
        doc_type = fields.get("document_type")

    pattern_ids = []
    try:
        candidates = diff_drafts(row["original_text"], req.submitted_text)
        classified = classify_edits(candidates, doc_type, base_url=LLM_BASE_URL, model=LLM_MODEL, api_key=LLM_API_KEY)
        for edit in classified:
            pid = upsert_pattern(edit, doc_type, draft_id, DSN)
            pattern_ids.append(pid)
    except Exception as e:
        logger.error(f"Edit classification failed for draft {draft_id}: {e}")

    return SubmitDraftResponse(
        draft_id=draft_id,
        status="submitted",
        patterns_extracted=len(pattern_ids),
        pattern_ids=pattern_ids,
    )


# ── Evidence ───────────────────────────────────────────────────────────────────

@app.get("/drafts/{draft_id}/evidence")
def get_draft_evidence(draft_id: str) -> list[dict]:
    row = get_draft(draft_id, DSN)
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    try:
        chunks = vector_query(
            queries=_RETRIEVAL_QUERIES,
            document_ids=row["document_ids"],
            top_k=3,
            min_score=0.25,
            host=CHROMA_HOST,
            port=CHROMA_PORT,
            device=EMBED_DEVICE,
        )
        return [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "page_number": c.page_number,
                "text": c.text,
                "ocr_confidence": c.ocr_confidence,
                "score": round(c.score, 3),
                "query": c.query,
            }
            for c in chunks
        ]
    except Exception as e:
        logger.error(f"Evidence retrieval failed for draft {draft_id}: {e}")
        return []


# ── Patterns ───────────────────────────────────────────────────────────────────

@app.get("/patterns", response_model=PatternListResponse)
def list_patterns(
    document_type: str | None = Query(None),
    section: str | None = Query(None),
    min_frequency: int = Query(1, ge=1),
) -> PatternListResponse:
    import psycopg2
    import psycopg2.extras
    with psycopg2.connect(DSN) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            conditions = ["frequency >= %s"]
            params: list = [min_frequency]
            if document_type:
                conditions.append("(document_type = %s OR document_type IS NULL)")
                params.append(document_type)
            if section:
                conditions.append("section = %s")
                params.append(section)
            where = "WHERE " + " AND ".join(conditions)
            cur.execute(f"SELECT * FROM edit_patterns {where} ORDER BY frequency DESC", params)
            rows = [dict(r) for r in cur.fetchall()]
    return PatternListResponse(
        total=len(rows),
        patterns=[PatternResponse(**r) for r in rows],
    )


@app.delete("/patterns/{pattern_id}", status_code=204)
def delete_pattern_endpoint(pattern_id: str) -> None:
    if not delete_pattern(pattern_id, DSN):
        raise HTTPException(status_code=404, detail="Pattern not found")


# ── Document delete ────────────────────────────────────────────────────────────

@app.delete("/documents/{document_id}", status_code=204)
def delete_document_endpoint(document_id: str) -> None:
    row = get_document(document_id, DSN)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    delete_by_document(document_id, host=CHROMA_HOST, port=CHROMA_PORT)

    for suffix in (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".txt"):
        f = DOCUMENT_DIR / f"{document_id}{suffix}"
        if f.exists():
            f.unlink()

    delete_document(document_id, DSN)
    logger.info(f"Deleted document {document_id}")


# ── Admin reset ────────────────────────────────────────────────────────────────

@app.post("/admin/reset")
def admin_reset() -> dict:
    import psycopg2
    import chromadb
    from chromadb.config import Settings

    with psycopg2.connect(DSN) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE drafts, documents, edit_patterns RESTART IDENTITY CASCADE")

    client = chromadb.HttpClient(
        host=CHROMA_HOST, port=CHROMA_PORT,
        settings=Settings(anonymized_telemetry=False),
    )
    try:
        client.delete_collection("lexai_chunks")
    except Exception:
        pass
    client.get_or_create_collection("lexai_chunks", metadata={"hnsw:space": "cosine"})

    removed = 0
    for f in DOCUMENT_DIR.iterdir():
        if f.is_file():
            f.unlink()
            removed += 1

    logger.info(f"Admin reset complete — {removed} file(s) removed")
    return {"status": "reset", "files_removed": removed}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _file_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}:
        return "image"
    if suffix in {".html", ".htm"}:
        return "html"
    return "text"


def _doc_row_to_schema(row: dict) -> DocumentResponse:
    import json
    fields = None
    if row.get("fields_json"):
        raw = row["fields_json"]
        data = raw if isinstance(raw, dict) else json.loads(raw)
        fields = ExtractedFieldsSchema(**data)
    return DocumentResponse(
        document_id=row["document_id"],
        filename=row["filename"],
        file_type=row["file_type"],
        upload_timestamp=row["upload_timestamp"],
        status=row["status"],
        page_count=row.get("page_count"),
        fields=fields,
        flags=row.get("flags") or [],
    )


def _draft_row_to_schema(row: dict) -> DraftResponse:
    import json
    citations_raw = row.get("citations_json") or []
    citations = citations_raw if isinstance(citations_raw, list) else json.loads(citations_raw)
    return DraftResponse(
        draft_id=row["draft_id"],
        document_ids=row["document_ids"],
        draft_type=row["draft_type"],
        created_at=row["created_at"],
        status=row["status"],
        draft_text=row["original_text"],
        ungrounded_sentences=row.get("ungrounded_sentences") or [],
        citations=citations,
        patterns_used=row.get("patterns_used") or [],
    )
