import pytest
from src.learning.edit_tracker import diff_drafts, _detect_section


ORIGINAL = """PARTIES

- Grantor: John Smith [doc-001, chunk-003]
- Trustee: First National Bank [doc-001, chunk-003]

KEY DATES

- Recording date: March 15, 2019 [doc-001, chunk-007]
- Maturity date: April 1, 2049 [doc-001, chunk-004]
"""

SUBMITTED = """PARTIES

- Grantor: Smith Family Trust, John Smith as Trustee [doc-001, chunk-003]
- Trustee: First National Bank [doc-001, chunk-003]

KEY DATES

- Recording date: 2019-03-15 [doc-001, chunk-007]
- Maturity date: April 1, 2049 [doc-001, chunk-004]
"""


def test_diff_detects_two_edits():
    candidates = diff_drafts(ORIGINAL, SUBMITTED)
    assert len(candidates) == 2


def test_diff_detects_correct_sections():
    candidates = diff_drafts(ORIGINAL, SUBMITTED)
    sections = {c.section for c in candidates}
    assert "parties" in sections
    assert "key_dates" in sections


def test_diff_captures_original_span():
    candidates = diff_drafts(ORIGINAL, SUBMITTED)
    originals = [c.original_span for c in candidates]
    assert any("John Smith" in o for o in originals)


def test_diff_captures_corrected_span():
    candidates = diff_drafts(ORIGINAL, SUBMITTED)
    corrected = [c.corrected_span for c in candidates]
    assert any("Smith Family Trust" in c for c in corrected)


def test_identical_drafts_produce_no_candidates():
    candidates = diff_drafts(ORIGINAL, ORIGINAL)
    assert candidates == []


def test_section_detection_finds_nearest_header():
    lines = ["PARTIES\n", "- Grantor: John Smith\n"]
    section = _detect_section(lines, 1)
    assert section == "parties"


def test_section_detection_unknown_when_no_header():
    lines = ["Some text without a header\n", "More text\n"]
    section = _detect_section(lines, 1)
    assert section == "unknown"
