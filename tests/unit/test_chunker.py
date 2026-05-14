import pytest
from src.extraction.chunker import chunk_document


_SENTENCE = (
    "This Agreement entered into as of the Effective Date by and between "
    "Link Plus Corporation and Axiometric LLC sets forth the terms and conditions "
    "under which the parties agree to collaborate on the development and distribution "
    "of wireless mesh networking technology and AMR devices and systems. "
)
SAMPLE_PAGES = [
    (1, _SENTENCE * 4, 0.95),
    (2, _SENTENCE * 4 + " The agreement was signed on March 15, 2019.", 0.92),
]


def test_chunk_count_is_nonzero():
    chunks = chunk_document("doc-test", SAMPLE_PAGES)
    assert len(chunks) > 0


def test_chunk_ids_are_unique():
    chunks = chunk_document("doc-test", SAMPLE_PAGES)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_chunk_ids_contain_document_id():
    chunks = chunk_document("doc-abc", SAMPLE_PAGES)
    for chunk in chunks:
        assert chunk.chunk_id.startswith("doc-abc")


def test_page_attribution():
    chunks = chunk_document("doc-test", SAMPLE_PAGES)
    page_numbers = {c.page_number for c in chunks}
    assert 1 in page_numbers


def test_ocr_confidence_carried_through():
    chunks = chunk_document("doc-test", SAMPLE_PAGES)
    for chunk in chunks:
        assert 0.0 <= chunk.ocr_confidence <= 1.0


def test_token_count_within_budget():
    chunks = chunk_document("doc-test", SAMPLE_PAGES, chunk_size=512)
    for chunk in chunks:
        assert chunk.token_count <= 640  # allow some headroom for overlap


def test_empty_pages_returns_no_chunks():
    chunks = chunk_document("doc-empty", [(1, "", 1.0)])
    assert chunks == []


def test_single_short_page():
    pages = [(1, "Short text.", 1.0)]
    chunks = chunk_document("doc-short", pages, min_chunk_size=1)
    assert len(chunks) == 1
    assert chunks[0].document_id == "doc-short"
