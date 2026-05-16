import json
from pathlib import Path

from src.retrieval.vector_store import RetrievedChunk
from src.extraction.field_extractor import ExtractedFields

DIVIDER = "─" * 41

SYSTEM_PROMPT = """You are a document analyst producing a structured Document Analysis Report.

Output rules — follow without exception:
1. Output PLAIN TEXT only. No markdown (no ##, no **, no backticks, no ---).
2. Section headers are ALL CAPS, left-aligned, no prefix symbols.
3. Every factual value must include [p.N] (page number) and [doc_id, chunk_id] (evidence citation). Use the EXACT document ID and chunk ID from the Evidence Chunks section — e.g. [doc-722944f0, doc-722944f0-chunk-002]. Never write the placeholder text "doc_id" or "chunk_id" literally.
4. If a value is not found in the evidence, write [NOT FOUND] — never guess or fabricate.
5. Omit any section where you have zero supporting evidence. Do not write empty sections.
6. Include every fact you find — omitting discovered information is a failure.
7. The document header block will be provided — output it verbatim as the first line of your response."""

DRAFT_TEMPLATE = """{system}

## Structured Fields
{fields_block}

## Evidence Chunks
(Each chunk: citation ID, page number [p.N], document ID, relevance score)
{evidence_block}
{patterns_block}
## Document Header (output this verbatim as the first block)

{doc_header}

## Task

Generate the Document Analysis Report. Start with the header block above (verbatim).
Then output only the sections below for which you have evidence. Use the exact format shown.

PARTIES

  • [Role]:    [Entity Name + ID/ABN/identifier if present]  [p.N] [doc_id, chunk_id]

KEY DATES

  • [Date Label]:    [Date]  [p.N] [doc_id, chunk_id]

KEY CLAUSES

  • [Clause Name]:   [Extracted Value]  [p.N] [doc_id, chunk_id]

FLAGS & RISKS

  ⚠ [Risk or quality issue description]  [p.N] [doc_id, chunk_id]

MATTER TIMELINE

  [Date] — [Event or Milestone]  [p.N] [doc_id, chunk_id]

OBLIGATION TRACKER

  [Party] — [Obligation] — Due: [Date or Condition]  [p.N] [doc_id, chunk_id]

RISK SUMMARY REPORT

  Overall: [Risk Level — High / Medium / Low]

  HIGH   ⚠ [item]  [p.N] [doc_id, chunk_id]
  MEDIUM ⚠ [item]  [p.N] [doc_id, chunk_id]
  LOW    ⚠ [item]  [p.N] [doc_id, chunk_id]

CLAUSE LIBRARY

  [Clause Type]: [Verbatim or near-verbatim extracted text]  [p.N] [doc_id, chunk_id]

PARTY PROFILE

  [Entity]: [Role, relationships, and any identifiers]  [p.N] [doc_id, chunk_id]

DUE DILIGENCE CHECKLIST

  [✓/✗] [Required Item] — [Found / Not Found]  [p.N] [doc_id, chunk_id]

ANOMALY / DEVIATION REPORT

  [Clause or Element] — [Deviation from standard]  [p.N] [doc_id, chunk_id]

DEPOSITION / TRANSCRIPT SUMMARY

  [Speaker]: [Key statement, position, or contradiction]  [p.N] [doc_id, chunk_id]

CASE LAW CITATION MAP

  [Case or Statute] — [Context of reference]  [p.N] [doc_id, chunk_id]

DOCUMENT GAP REPORT

  [Expected Element] — [Present / Missing / Illegible]  [p.N if locatable]

AUDIT TRAIL

  [Actor] — [Action] — [Timestamp]  [p.N] [doc_id, chunk_id]

SOURCE GROUNDING

  • [Field or Topic]: [Value]  [p.N] [doc_id, chunk_id]
"""


def build_prompt(
    fields_by_doc: dict[str, ExtractedFields],
    chunks: list[RetrievedChunk],
    patterns: list[dict] | None = None,
    doc_meta: dict[str, dict] | None = None,
) -> str:
    fields_block = _build_fields_block(fields_by_doc)
    evidence_block = _build_evidence_block(chunks)
    patterns_block = _build_patterns_block(patterns or [])
    doc_header = _build_doc_header(fields_by_doc, doc_meta or {})

    return DRAFT_TEMPLATE.format(
        system=SYSTEM_PROMPT,
        fields_block=fields_block,
        evidence_block=evidence_block,
        patterns_block=patterns_block,
        doc_header=doc_header,
    )


def _build_doc_header(
    fields_by_doc: dict[str, ExtractedFields],
    doc_meta: dict[str, dict],
) -> str:
    doc_id = next(iter(fields_by_doc), "")
    fields = fields_by_doc.get(doc_id)
    meta = doc_meta.get(doc_id, {})

    filename = meta.get("filename", doc_id)
    title = Path(filename).stem.replace("_", " ").replace("-", " ").title()
    doc_type = (fields.document_type if fields and fields.document_type else "Unknown")
    page_count = meta.get("page_count") or "?"

    # Best available date: first key_date entry > upload timestamp
    date = ""
    if fields:
        for kd in (fields.key_dates or []):
            if kd.get("date"):
                date = kd["date"]
                break
    if not date and meta.get("upload_timestamp"):
        ts = meta["upload_timestamp"]
        date = str(ts)[:10] if ts else ""

    return (
        f"{DIVIDER}\n\n"
        f"DOCUMENT: {title}\n\n"
        f"TYPE: {doc_type}  |  PAGES: {page_count}  |  DATE: {date or 'N/A'}\n\n"
        f"{DIVIDER}"
    )


_FIELDS_MAX_CHARS = 8000


def _build_fields_block(fields_by_doc: dict[str, ExtractedFields]) -> str:
    lines = []
    for doc_id, fields in fields_by_doc.items():
        lines.append(f"### {doc_id}")
        raw = json.dumps(fields.to_dict(), indent=2, default=str)
        if len(raw) > _FIELDS_MAX_CHARS:
            raw = raw[:_FIELDS_MAX_CHARS] + "\n... [truncated for context length]"
        lines.append(raw)
    return "\n".join(lines)


def _build_evidence_block(chunks: list[RetrievedChunk]) -> str:
    lines = []
    for c in chunks:
        confidence_note = " [LOW_CONFIDENCE]" if c.ocr_confidence < 0.40 else ""
        lines.append(
            f"[{c.chunk_id}] [p.{c.page_number}] doc={c.document_id} score={c.score:.2f}{confidence_note}"
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
