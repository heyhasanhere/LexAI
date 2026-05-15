import json
import re
from dataclasses import dataclass, field
from typing import Any


def _vllm_extra(base_url: str) -> dict:
    """Return extra_body for Qwen3 thinking suppression when talking to vLLM.
    OpenAI's API rejects unknown extra_body fields, so we only send this for
    non-OpenAI endpoints."""
    if "openai.com" in base_url:
        return {}
    return {"chat_template_kwargs": {"enable_thinking": False}}

from openai import OpenAI

from src.utils.logger import get_logger

logger = get_logger(__name__)

EXTRACTION_PROMPT = """You are a document analyst. Extract all structured information from the document text below.
The text uses [PAGE N] markers to indicate page numbers. Use these to produce accurate "page" integer values in your output.

Return a JSON object. Only include sections where you actually found data — omit empty sections entirely.
Use null for individual fields that are absent. Page numbers must be integers (or null if truly unknown).

{{
  "document_type": "<type or null>",
  "parties": [{{"role": "<role>", "name": "<name>", "identifier": "<ABN/ID/number or null>", "page": <int or null>}}],
  "key_dates": [{{"label": "<date label>", "date": "<date>", "page": <int or null>, "alert": "<deadline warning or null>"}}],
  "key_clauses": [{{"name": "<clause name>", "value": "<extracted value>", "page": <int or null>}}],
  "flags_and_risks": [{{"description": "<risk or quality issue>", "page": <int or null>}}],
  "matter_timeline": [{{"date": "<date>", "event": "<event or milestone>", "page": <int or null>}}],
  "obligation_tracker": [{{"party": "<party>", "obligation": "<obligation>", "due": "<date or condition or null>", "page": <int or null>}}],
  "risk_summary": {{"overall": "<summary>", "level": "High|Medium|Low", "items": [{{"severity": "High|Medium|Low", "description": "<item>", "page": <int or null>}}]}},
  "clause_library": [{{"clause_type": "<type>", "text": "<verbatim or near-verbatim text>", "page": <int or null>}}],
  "party_profile": [{{"entity": "<name>", "role": "<role>", "identifiers": "<IDs or null>", "page": <int or null>}}],
  "due_diligence_checklist": [{{"item": "<required item>", "found": true/false, "page": <int or null>}}],
  "anomaly_report": [{{"clause": "<clause or element>", "deviation": "<deviation from standard>", "page": <int or null>}}],
  "transcript_summary": [{{"speaker": "<name>", "statement": "<key statement or position>", "page": <int or null>}}],
  "case_law_citations": [{{"case": "<case or statute>", "context": "<context of reference>", "page": <int or null>}}],
  "document_gap_report": [{{"expected": "<expected element>", "status": "Present|Missing|Illegible"}}],
  "audit_trail": [{{"actor": "<actor>", "action": "<action>", "timestamp": "<timestamp>", "page": <int or null>}}],
  "source_grounding": [{{"field": "<field or topic>", "value": "<value>", "page": <int or null>}}],
  "extraction_notes": "<brief description of the document and notable extraction points, or null>",
  "flags": ["<structural or quality issue only>"]
}}

Rules:
- document_type: identify the actual document type (contract, invoice, deed, report, letter, memo, medical record, etc.)
- parties: any named people or organisations and their roles
- key_dates: all dates that matter (signing, recording, due dates, deadlines, expirations)
- key_clauses: important terms, conditions, and provisions found in the document
- flags_and_risks: both quality issues AND substantive risks (missing signatures, unusual clauses, liabilities)
- source_grounding: important facts not captured in other sections above
- flags (array): structural/quality issues only (missing pages, OCR problems, truncated content, conflicting information)
- Omit any section where you found zero relevant data
- Return JSON only. No text outside the JSON object.

Document text:
{text}"""

_LEVEL_RANK = {"High": 3, "Medium": 2, "Low": 1}


@dataclass
class ExtractedFields:
    document_type: str | None = None
    parties: list[dict] = field(default_factory=list)
    key_dates: list[dict] = field(default_factory=list)
    key_clauses: list[dict] = field(default_factory=list)
    flags_and_risks: list[dict] = field(default_factory=list)
    matter_timeline: list[dict] = field(default_factory=list)
    obligation_tracker: list[dict] = field(default_factory=list)
    risk_summary: dict | None = None
    clause_library: list[dict] = field(default_factory=list)
    party_profile: list[dict] = field(default_factory=list)
    due_diligence_checklist: list[dict] = field(default_factory=list)
    anomaly_report: list[dict] = field(default_factory=list)
    transcript_summary: list[dict] = field(default_factory=list)
    case_law_citations: list[dict] = field(default_factory=list)
    document_gap_report: list[dict] = field(default_factory=list)
    audit_trail: list[dict] = field(default_factory=list)
    source_grounding: list[dict] = field(default_factory=list)
    extraction_notes: str | None = None
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_type": self.document_type,
            "parties": self.parties,
            "key_dates": self.key_dates,
            "key_clauses": self.key_clauses,
            "flags_and_risks": self.flags_and_risks,
            "matter_timeline": self.matter_timeline,
            "obligation_tracker": self.obligation_tracker,
            "risk_summary": self.risk_summary,
            "clause_library": self.clause_library,
            "party_profile": self.party_profile,
            "due_diligence_checklist": self.due_diligence_checklist,
            "anomaly_report": self.anomaly_report,
            "transcript_summary": self.transcript_summary,
            "case_law_citations": self.case_law_citations,
            "document_gap_report": self.document_gap_report,
            "audit_trail": self.audit_trail,
            "source_grounding": self.source_grounding,
            "extraction_notes": self.extraction_notes,
            "flags": self.flags,
        }


def extract_fields(
    text: str,
    base_url: str = "http://localhost:8080/v1",
    model: str = "Qwen/Qwen3-14B-AWQ",
    api_key: str = "local",
    max_tokens: int = 4096,
    max_chunk_chars: int = 40000,
) -> ExtractedFields:
    chunks = _split_into_page_chunks(text, max_chunk_chars)
    if len(chunks) == 1:
        return _extract_single(chunks[0], base_url, model, api_key, max_tokens)

    logger.info(f"Document split into {len(chunks)} chunk(s) for multi-turn extraction")
    results = []
    for i, chunk in enumerate(chunks):
        logger.info(f"Extracting chunk {i + 1}/{len(chunks)}")
        results.append(_extract_single(chunk, base_url, model, api_key, max_tokens))

    return _merge_fields(results)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _split_into_page_chunks(text: str, max_chars: int) -> list[str]:
    """Split page-annotated text into chunks no larger than max_chars, breaking on [PAGE N] boundaries."""
    pages = re.split(r"(?=\[PAGE \d+\])", text)
    chunks: list[str] = []
    current = ""
    for page in pages:
        if not page.strip():
            continue
        if current and len(current) + len(page) > max_chars:
            chunks.append(current.strip())
            current = page
        else:
            current += ("\n\n" if current else "") + page.strip()
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


def _extract_single(
    text: str,
    base_url: str,
    model: str,
    api_key: str,
    max_tokens: int,
) -> ExtractedFields:
    client = OpenAI(base_url=base_url, api_key=api_key)
    prompt = EXTRACTION_PROMPT.format(text=text)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.0,
            extra_body=_vllm_extra(base_url),
        )
        raw = response.choices[0].message.content.strip()

        if "<think>" in raw:
            raw = raw.split("</think>")[-1].strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)

        return ExtractedFields(
            document_type=data.get("document_type"),
            parties=data.get("parties") or [],
            key_dates=data.get("key_dates") or [],
            key_clauses=data.get("key_clauses") or [],
            flags_and_risks=data.get("flags_and_risks") or [],
            matter_timeline=data.get("matter_timeline") or [],
            obligation_tracker=data.get("obligation_tracker") or [],
            risk_summary=data.get("risk_summary") or None,
            clause_library=data.get("clause_library") or [],
            party_profile=data.get("party_profile") or [],
            due_diligence_checklist=data.get("due_diligence_checklist") or [],
            anomaly_report=data.get("anomaly_report") or [],
            transcript_summary=data.get("transcript_summary") or [],
            case_law_citations=data.get("case_law_citations") or [],
            document_gap_report=data.get("document_gap_report") or [],
            audit_trail=data.get("audit_trail") or [],
            source_grounding=data.get("source_grounding") or [],
            extraction_notes=data.get("extraction_notes"),
            flags=data.get("flags") or [],
        )

    except json.JSONDecodeError as e:
        logger.error(f"Field extraction JSON parse failed: {e}")
        return ExtractedFields(extraction_notes=f"JSON parse error: {e}", flags=["extraction_failed"])
    except Exception as e:
        logger.error(f"Field extraction failed: {e}")
        return ExtractedFields(extraction_notes=str(e), flags=["extraction_failed"])


def _merge_fields(fields_list: list[ExtractedFields]) -> ExtractedFields:
    """Combine results from multiple extraction passes into a single ExtractedFields."""
    merged = ExtractedFields()

    for f in fields_list:
        if not merged.document_type and f.document_type:
            merged.document_type = f.document_type

        merged.parties.extend(f.parties)
        merged.key_dates.extend(f.key_dates)
        merged.key_clauses.extend(f.key_clauses)
        merged.flags_and_risks.extend(f.flags_and_risks)
        merged.matter_timeline.extend(f.matter_timeline)
        merged.obligation_tracker.extend(f.obligation_tracker)
        merged.clause_library.extend(f.clause_library)
        merged.party_profile.extend(f.party_profile)
        merged.due_diligence_checklist.extend(f.due_diligence_checklist)
        merged.anomaly_report.extend(f.anomaly_report)
        merged.transcript_summary.extend(f.transcript_summary)
        merged.case_law_citations.extend(f.case_law_citations)
        merged.document_gap_report.extend(f.document_gap_report)
        merged.audit_trail.extend(f.audit_trail)
        merged.source_grounding.extend(f.source_grounding)

        # risk_summary: keep highest level, merge items
        if f.risk_summary:
            if not merged.risk_summary:
                merged.risk_summary = dict(f.risk_summary)
                merged.risk_summary["items"] = list(f.risk_summary.get("items") or [])
            else:
                existing_rank = _LEVEL_RANK.get(merged.risk_summary.get("level", "Low"), 1)
                new_rank = _LEVEL_RANK.get(f.risk_summary.get("level", "Low"), 1)
                if new_rank > existing_rank:
                    merged.risk_summary["level"] = f.risk_summary["level"]
                    merged.risk_summary["overall"] = f.risk_summary["overall"]
                merged.risk_summary["items"] = (
                    merged.risk_summary.get("items") or []
                ) + (f.risk_summary.get("items") or [])

        # extraction_notes: concatenate non-empty notes
        if f.extraction_notes:
            merged.extraction_notes = (
                f"{merged.extraction_notes} | {f.extraction_notes}"
                if merged.extraction_notes
                else f.extraction_notes
            )

        # flags: extend, deduplicate, preserve order
        for flag in f.flags:
            if flag not in merged.flags:
                merged.flags.append(flag)

    return merged
