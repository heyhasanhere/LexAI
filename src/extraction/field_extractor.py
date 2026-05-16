import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from src.utils.llm_client import chat_extra_body, get_client
from src.utils.logger import get_logger

logger = get_logger(__name__)

EXTRACTION_PROMPT = """You are a document analyst. Extract structured information from the document text below.
The text uses [PAGE N] markers to indicate page numbers. Use these for "page" integer values.

Return ONLY a JSON object. Omit any section where you found zero relevant data.
Use null for absent individual fields. Page numbers must be integers (or null).

{{
  "document_type": "<type or null>",
  "parties": [{{"role": "<role>", "name": "<name>", "page": <int or null>}}],
  "key_dates": [{{"label": "<label>", "date": "<date>", "page": <int or null>}}],
  "key_clauses": [{{"name": "<clause name>", "value": "<extracted value>", "page": <int or null>}}],
  "flags_and_risks": [{{"description": "<risk or quality issue>", "page": <int or null>}}],
  "risk_summary": {{"overall": "<one-sentence summary>", "level": "High|Medium|Low"}},
  "extraction_notes": "<brief notes or null>",
  "flags": ["<structural/quality issue>"]
}}

Rules:
- document_type: identify the document type (contract, deed, invoice, letter, etc.)
- parties: named people or organisations and their roles
- key_dates: signing date, deadlines, expirations, recording dates
- key_clauses: the most important terms, conditions, and obligations
- flags_and_risks: quality issues (missing pages, illegible text) and substantive risks (unusual clauses, liabilities)
- flags array: structural/quality issues only
- Return JSON only. No prose outside the JSON object.

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
    model: str = "Qwen/Qwen3-4B-AWQ",
    api_key: str = "local",
    provider: str = "vllm",
    max_tokens: int = 3072,
    max_chunk_chars: int = 28000,
) -> ExtractedFields:
    chunks = _split_into_page_chunks(text, max_chunk_chars)
    if len(chunks) == 1:
        return _extract_single(chunks[0], base_url, model, api_key, max_tokens, provider)

    logger.info(f"Document split into {len(chunks)} chunk(s) for multi-turn extraction")
    results = []
    for i, chunk in enumerate(chunks):
        logger.info(f"Extracting chunk {i + 1}/{len(chunks)}")
        results.append(_extract_single(chunk, base_url, model, api_key, max_tokens, provider))

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
    provider: str = "vllm",
    _retries: int = 3,
) -> ExtractedFields:
    client = get_client(provider, base_url, api_key)
    prompt = EXTRACTION_PROMPT.format(text=text)

    for attempt in range(_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.0,
                extra_body=chat_extra_body(provider),
            )
            raw = response.choices[0].message.content.strip()

            if "<think>" in raw:
                raw = raw.split("</think>")[-1].strip()

            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            if not raw:
                raise ValueError("Empty response from LLM")

            # Repair truncated JSON by trimming to last complete top-level value
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                repaired = _repair_truncated_json(raw)
                if repaired is None:
                    raise
                logger.warning("Extraction response was truncated; parsed partial result")
                data = repaired

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

        except Exception as e:
            msg = str(e)
            # Rate limit — back off and retry
            if "rate_limit" in msg or "429" in msg or "too many" in msg.lower():
                wait = 60 * (attempt + 1)
                logger.warning(f"Rate limit hit on attempt {attempt + 1}; retrying in {wait}s")
                time.sleep(wait)
                continue
            if attempt < _retries - 1 and ("timeout" in msg.lower() or "connection" in msg.lower()):
                time.sleep(5 * (attempt + 1))
                continue
            logger.error(f"Field extraction failed: {e}")
            return ExtractedFields(extraction_notes=msg, flags=["extraction_failed"])

    logger.error("Field extraction exhausted all retries")
    return ExtractedFields(flags=["extraction_failed"])


def _repair_truncated_json(raw: str) -> dict | None:
    """Try to recover a valid JSON object from a truncated LLM response.

    Scans backward in 50-char steps, closing any open brackets at each candidate
    boundary. Returns the parsed dict from the longest valid prefix found.
    """
    def _try_close(s: str) -> dict | None:
        s = s.rstrip().rstrip(",").rstrip()
        stack: list[str] = []
        in_str = False
        esc = False
        for ch in s:
            if esc:
                esc = False
                continue
            if ch == "\\" and in_str:
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack and stack[-1] == ch:
                stack.pop()
        # If we're still inside a string literal the boundary is mid-token — skip
        if in_str:
            return None
        candidate = s + "".join(reversed(stack))
        try:
            result = json.loads(candidate)
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            return None

    step = 50
    for end in range(len(raw), 0, -step):
        result = _try_close(raw[:end])
        if result is not None:
            return result
    return None


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
