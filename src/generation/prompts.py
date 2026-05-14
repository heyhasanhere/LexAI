import json
from src.retrieval.vector_store import RetrievedChunk
from src.extraction.field_extractor import ExtractedFields

SYSTEM_PROMPT = """You are a legal document analyst producing a first-pass internal Case Fact Summary.

Rules you must follow without exception:
1. Every factual claim must end with a citation in the format [doc_id, chunk_id].
2. If you cannot support a claim from the provided evidence, write [UNSUPPORTED] instead of guessing.
3. Do not introduce any information not present in the evidence or structured fields below.
4. Do not speculate about missing information — flag it instead.

Output format: structured markdown with the sections listed in the task instruction."""

DRAFT_TEMPLATE = """{system}

## Structured Fields
{fields_block}

## Evidence Chunks
{evidence_block}
{patterns_block}
## Task

Generate a Case Fact Summary with these sections:
1. Document Inventory
2. Parties
3. Key Dates and Instruments
4. Property / Subject Matter (if applicable)
5. Flags and Gaps
6. Suggested Next Steps (based only on detected gaps)

Follow the citation and grounding rules above strictly."""


def build_prompt(
    fields_by_doc: dict[str, ExtractedFields],
    chunks: list[RetrievedChunk],
    patterns: list[dict] | None = None,
) -> str:
    fields_block = _build_fields_block(fields_by_doc)
    evidence_block = _build_evidence_block(chunks)
    patterns_block = _build_patterns_block(patterns or [])

    return DRAFT_TEMPLATE.format(
        system=SYSTEM_PROMPT,
        fields_block=fields_block,
        evidence_block=evidence_block,
        patterns_block=patterns_block,
    )


def _build_fields_block(fields_by_doc: dict[str, ExtractedFields]) -> str:
    lines = []
    for doc_id, fields in fields_by_doc.items():
        lines.append(f"### {doc_id}")
        lines.append(json.dumps(fields.to_dict(), indent=2, default=str))
    return "\n".join(lines)


def _build_evidence_block(chunks: list[RetrievedChunk]) -> str:
    lines = []
    for c in chunks:
        confidence_note = " [low_confidence]" if c.ocr_confidence < 0.40 else ""
        lines.append(
            f"[{c.chunk_id}] doc={c.document_id} page={c.page_number}"
            f" score={c.score:.2f}{confidence_note}"
        )
        lines.append(c.text)
        lines.append("")
    return "\n".join(lines)


def _build_patterns_block(patterns: list[dict]) -> str:
    if not patterns:
        return ""
    lines = ["\n## Learned Preferences from Operator Edits\n"]
    for i, p in enumerate(patterns, 1):
        lines.append(
            f"{i}. [{p.get('section', '')} / {p.get('edit_type', '')}]\n"
            f"   Trigger: {p.get('trigger', '')}\n"
            f"   Before: {p.get('original_text', '')}\n"
            f"   After:  {p.get('corrected_text', '')}\n"
        )
    return "\n".join(lines)
