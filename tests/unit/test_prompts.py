import pytest
from src.extraction.field_extractor import ExtractedFields
from src.generation.prompts import build_prompt, _build_evidence_block, _build_patterns_block
from src.retrieval.vector_store import RetrievedChunk


def _make_chunk(chunk_id: str, text: str, score: float = 0.8, confidence: float = 0.95) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc-001",
        page_number=1,
        text=text,
        ocr_confidence=confidence,
        score=score,
        query="test query",
    )


def test_prompt_contains_system_rules():
    fields = {"doc-001": ExtractedFields()}
    chunks = [_make_chunk("doc-001-chunk-000", "Some legal text.")]
    prompt = build_prompt(fields, chunks)
    assert "citation" in prompt.lower()
    assert "[UNSUPPORTED]" in prompt


def test_prompt_contains_evidence_chunk():
    fields = {"doc-001": ExtractedFields()}
    chunks = [_make_chunk("doc-001-chunk-000", "The grantor is John Smith.")]
    prompt = build_prompt(fields, chunks)
    assert "The grantor is John Smith." in prompt


def test_prompt_contains_chunk_id():
    fields = {"doc-001": ExtractedFields()}
    chunks = [_make_chunk("doc-001-chunk-007", "Some text.")]
    prompt = build_prompt(fields, chunks)
    assert "doc-001-chunk-007" in prompt


def test_low_confidence_chunk_is_flagged():
    fields = {"doc-001": ExtractedFields()}
    chunks = [_make_chunk("doc-001-chunk-000", "Unclear text.", confidence=0.30)]
    evidence = _build_evidence_block(chunks)
    assert "low_confidence" in evidence


def test_no_patterns_block_when_empty():
    result = _build_patterns_block([])
    assert result == ""


def test_patterns_block_included_when_present():
    patterns = [{
        "section": "parties",
        "edit_type": "correction",
        "trigger": "When entity name present, list as primary party.",
        "original_text": "Grantor: John Smith",
        "corrected_text": "Grantor: Smith Family Trust",
    }]
    block = _build_patterns_block(patterns)
    assert "parties" in block
    assert "Grantor: John Smith" in block


def test_prompt_without_patterns_has_no_learned_preferences():
    fields = {"doc-001": ExtractedFields()}
    chunks = [_make_chunk("doc-001-chunk-000", "Text.")]
    prompt = build_prompt(fields, chunks, patterns=[])
    assert "Learned Preferences" not in prompt
