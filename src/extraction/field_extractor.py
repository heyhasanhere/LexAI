import json
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from src.utils.logger import get_logger

logger = get_logger(__name__)

EXTRACTION_PROMPT = """You are a legal document analyst. Extract structured fields from the document text below.

Return a JSON object with these fields (use null for anything you cannot extract with confidence):
{
  "document_type": string or null,
  "parties": [{"role": string, "name": string or null, "entity_type": string or null, "confidence": "high"|"medium"|"low"}],
  "property_address": string or null,
  "legal_description": string or null,
  "recording_date": "YYYY-MM-DD" or null,
  "instrument_number": string or null,
  "loan_amount": number or null,
  "maturity_date": "YYYY-MM-DD" or null,
  "notary_present": boolean or null,
  "key_value_pairs": [{"key": string, "value": string}],
  "extraction_notes": string or null,
  "flags": [string]
}

Rules:
- document_type: classify as deed_of_trust, lien_release, title_commitment, affiliate_agreement, promissory_note, or other
- parties: include all named parties with their roles
- flags: list any structural issues — missing pages, illegible sections, conflicting information, correction fluid, etc.
- extraction_notes: explain any fields you could not extract and why
- Return JSON only. No explanation outside the JSON object.

Document text:
{text}"""


@dataclass
class ExtractedFields:
    document_type: str | None = None
    parties: list[dict] = field(default_factory=list)
    property_address: str | None = None
    legal_description: str | None = None
    recording_date: str | None = None
    instrument_number: str | None = None
    loan_amount: float | None = None
    maturity_date: str | None = None
    notary_present: bool | None = None
    key_value_pairs: list[dict] = field(default_factory=list)
    extraction_notes: str | None = None
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_type": self.document_type,
            "parties": self.parties,
            "property_address": self.property_address,
            "legal_description": self.legal_description,
            "recording_date": self.recording_date,
            "instrument_number": self.instrument_number,
            "loan_amount": self.loan_amount,
            "maturity_date": self.maturity_date,
            "notary_present": self.notary_present,
            "key_value_pairs": self.key_value_pairs,
            "extraction_notes": self.extraction_notes,
            "flags": self.flags,
        }


def extract_fields(
    text: str,
    base_url: str = "http://localhost:8080/v1",
    model: str = "mistralai/Mistral-Small-3.1-24B-Instruct",
    max_tokens: int = 1024,
    max_text_chars: int = 12000,
) -> ExtractedFields:
    if len(text) > max_text_chars:
        # Use first 80% and last 20% of the budget to capture header and signature blocks
        head = int(max_text_chars * 0.8)
        tail = max_text_chars - head
        text = text[:head] + "\n\n[... document truncated ...]\n\n" + text[-tail:]
        logger.warning(f"Document text truncated to {max_text_chars} chars for extraction")

    client = OpenAI(base_url=base_url, api_key="local")
    prompt = EXTRACTION_PROMPT.format(text=text)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.0,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        return ExtractedFields(
            document_type=data.get("document_type"),
            parties=data.get("parties") or [],
            property_address=data.get("property_address"),
            legal_description=data.get("legal_description"),
            recording_date=data.get("recording_date"),
            instrument_number=data.get("instrument_number"),
            loan_amount=data.get("loan_amount"),
            maturity_date=data.get("maturity_date"),
            notary_present=data.get("notary_present"),
            key_value_pairs=data.get("key_value_pairs") or [],
            extraction_notes=data.get("extraction_notes"),
            flags=data.get("flags") or [],
        )

    except json.JSONDecodeError as e:
        logger.error(f"Field extraction JSON parse failed: {e}")
        return ExtractedFields(extraction_notes=f"JSON parse error: {e}", flags=["extraction_failed"])
    except Exception as e:
        logger.error(f"Field extraction failed: {e}")
        return ExtractedFields(extraction_notes=str(e), flags=["extraction_failed"])
