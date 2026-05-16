"""
Integration tests for the full ingestion pipeline.
Requires: sample_data/inputs/ populated with real documents.
Does NOT require backing services (uses in-memory Chroma, skips LLM calls).

Run with:
    pytest tests/integration/test_ingestion_pipeline.py -v
"""
import pytest
from pathlib import Path

CUAD_DIR = Path("sample_data/cuad")
RVL_DIR = Path("sample_data/rvl_cdip")

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


def test_cuad_pdf_has_high_ocr_confidence():
    from src.ingestion.loader import load_document
    pdf = next(CUAD_DIR.glob("*.pdf"))
    doc = load_document(pdf)
    avg_conf = sum(p.ocr_confidence for p in doc.pages) / len(doc.pages)
    assert avg_conf > 0.70


def test_handwritten_image_loads_and_flags_low_confidence():
    from src.ingestion.loader import load_document
    imgs = list(RVL_DIR.glob("handwritten_*.jpg"))
    if not imgs:
        pytest.skip("No handwritten images found")
    doc = load_document(imgs[0])
    assert doc.page_count == 1
    # Handwritten docs should have at least some low-confidence pages
    confidences = [p.ocr_confidence for p in doc.pages]
    assert min(confidences) < 0.80


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
    import chromadb
    import src.retrieval.vector_store as vs

    client = chromadb.Client()
    vs._get_client = lambda host, port: client

    from src.ingestion.loader import load_document
    from src.extraction.chunker import chunk_document
    from src.retrieval.vector_store import upsert_chunks, query

    pdf = next(CUAD_DIR.glob("*.pdf"))
    doc = load_document(pdf)
    pages = [(p.page_number, p.text, p.ocr_confidence) for p in doc.pages]
    chunks = chunk_document("doc-integ-001", pages)

    upsert_chunks(chunks, device="cpu", host="localhost", port=8001)

    results = query(
        queries=["parties agreement"],
        document_ids=["doc-integ-001"],
        top_k=3,
        min_score=0.2,
        device="cpu",
        host="localhost",
        port=8001,
    )

    assert len(results) > 0
    assert all(r.score >= 0.2 for r in results)
    assert all(r.document_id == "doc-integ-001" for r in results)
