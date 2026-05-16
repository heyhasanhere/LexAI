"""
Integration tests for the full ingestion pipeline.
Requires: sample_data/inputs/ populated with real documents.
The retrieval test requires a live Postgres+pgvector instance.
Set TEST_DSN env var to override the default connection string.

Run with:
    pytest tests/integration/test_ingestion_pipeline.py -v
"""
import os
import pytest
from pathlib import Path

CUAD_DIR = Path("sample_data/cuad")
RVL_DIR  = Path("sample_data/rvl_cdip")
TEST_DSN  = os.getenv("TEST_DSN", "postgresql://ld:ld@localhost:5432/lexai")

pytestmark = pytest.mark.skipif(
    not CUAD_DIR.exists(),
    reason="sample_data not found",
)


def test_cuad_pdf_loads_and_extracts_text():
    from src.ingestion.loader import load_document
    pdf = next(CUAD_DIR.glob("*.pdf"))
    doc = load_document(pdf)
    assert doc.page_count > 0
    assert len(doc.full_text) > 100


def test_cuad_pdf_pages_have_text():
    from src.ingestion.loader import load_document
    pdf = next(CUAD_DIR.glob("*.pdf"))
    doc = load_document(pdf)
    # Marker returns ocr_confidence=1.0 — check that pages actually have content
    assert all(len(p.text.strip()) > 0 for p in doc.pages if not p.failed)


def test_image_file_loads():
    imgs = list(RVL_DIR.glob("*.jpg")) if RVL_DIR.exists() else []
    if not imgs:
        pytest.skip("No images found in sample_data/rvl_cdip")
    from src.ingestion.loader import load_document
    doc = load_document(imgs[0])
    assert doc.page_count >= 1
    assert doc.file_type == "image"


def test_chunker_produces_chunks_from_cuad_pdf():
    from src.ingestion.loader import load_document
    from src.extraction.chunker import chunk_document
    pdf = next(CUAD_DIR.glob("*.pdf"))
    doc = load_document(pdf)
    pages = [(p.page_number, p.text, p.ocr_confidence) for p in doc.pages]
    chunks = chunk_document("doc-test", pages)
    assert len(chunks) > 0
    assert all(c.token_count > 0 for c in chunks)


def test_full_pipeline_ingestion_and_retrieval():
    pytest.importorskip("psycopg2")
    import psycopg2
    try:
        conn = psycopg2.connect(TEST_DSN, connect_timeout=3)
        conn.close()
    except Exception:
        pytest.skip("No Postgres+pgvector instance available at TEST_DSN")

    from src.ingestion.loader import load_document
    from src.extraction.chunker import chunk_document
    from src.retrieval.vector_store import upsert_chunks, query, delete_by_document

    doc_id = "doc-integ-test-001"
    pdf = next(CUAD_DIR.glob("*.pdf"))
    doc = load_document(pdf)
    pages = [(p.page_number, p.text, p.ocr_confidence) for p in doc.pages]
    chunks = chunk_document(doc_id, pages)

    try:
        upsert_chunks(chunks, device="cpu", dsn=TEST_DSN)

        results = query(
            queries=["parties agreement"],
            document_ids=[doc_id],
            top_k=3,
            min_score=0.2,
            device="cpu",
            dsn=TEST_DSN,
        )

        assert len(results) > 0
        assert all(r.score >= 0.2 for r in results)
        assert all(r.document_id == doc_id for r in results)
    finally:
        delete_by_document(doc_id, dsn=TEST_DSN)
