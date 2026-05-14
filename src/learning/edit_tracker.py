import difflib
import json
import re
from dataclasses import dataclass

from openai import OpenAI

from src.utils.logger import get_logger

logger = get_logger(__name__)

SECTION_HEADER = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)

CLASSIFY_PROMPT = """You are reviewing an operator's edit to a legal document draft.

Original text:
{original}

Operator's corrected text:
{corrected}

Context before:
{context_before}

Context after:
{context_after}

Classify this edit and return JSON only:
{{
  "edit_type": "correction" | "addition" | "deletion" | "reformat",
  "trigger": "<one sentence: when should this pattern apply in the future>",
  "generalizable": true | false
}}

generalizable=true means this is a structural or formatting preference applicable to similar documents.
generalizable=false means it is specific to this document's content and should not be reused."""


@dataclass
class EditCandidate:
    section: str
    original_span: str
    corrected_span: str
    context_before: str
    context_after: str


@dataclass
class ClassifiedEdit:
    section: str
    original_text: str
    corrected_text: str
    edit_type: str
    trigger: str
    generalizable: bool


def diff_drafts(original: str, submitted: str) -> list[EditCandidate]:
    original_lines = original.splitlines(keepends=True)
    submitted_lines = submitted.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, original_lines, submitted_lines)
    candidates = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        original_span = "".join(original_lines[i1:i2]).strip()
        corrected_span = "".join(submitted_lines[j1:j2]).strip()

        if not original_span and not corrected_span:
            continue

        context_before = "".join(original_lines[max(0, i1 - 2):i1]).strip()
        context_after = "".join(original_lines[i2:i2 + 2]).strip()
        section = _detect_section(original_lines, i1)

        candidates.append(EditCandidate(
            section=section,
            original_span=original_span,
            corrected_span=corrected_span,
            context_before=context_before,
            context_after=context_after,
        ))

    logger.info(f"Diff produced {len(candidates)} edit candidate(s)")
    return candidates


def classify_edits(
    candidates: list[EditCandidate],
    document_type: str | None,
    base_url: str = "http://localhost:8080/v1",
    model: str = "mistralai/Mistral-Small-3.1-24B-Instruct",
) -> list[ClassifiedEdit]:
    if not candidates:
        return []

    client = OpenAI(base_url=base_url, api_key="local")
    classified = []

    for candidate in candidates:
        prompt = CLASSIFY_PROMPT.format(
            original=candidate.original_span,
            corrected=candidate.corrected_span,
            context_before=candidate.context_before,
            context_after=candidate.context_after,
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=256,
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            data = json.loads(raw)

            if not data.get("generalizable", False):
                logger.info(f"Edit in section '{candidate.section}' marked non-generalizable, skipping")
                continue

            classified.append(ClassifiedEdit(
                section=candidate.section,
                original_text=candidate.original_span,
                corrected_text=candidate.corrected_span,
                edit_type=data.get("edit_type", "correction"),
                trigger=data.get("trigger", ""),
                generalizable=True,
            ))

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Edit classification failed: {e}")
            continue

    logger.info(f"Classified {len(classified)} generalizable edit(s)")
    return classified


def _detect_section(lines: list[str], line_index: int) -> str:
    for i in range(line_index, -1, -1):
        match = SECTION_HEADER.match(lines[i].rstrip())
        if match:
            return match.group(1).strip().lower().replace(" ", "_")
    return "unknown"
