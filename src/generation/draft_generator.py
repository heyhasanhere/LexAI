import re
from dataclasses import dataclass, field

from openai import OpenAI

from src.extraction.field_extractor import ExtractedFields
from src.generation.prompts import build_prompt
from src.retrieval.vector_store import RetrievedChunk
from src.utils.logger import get_logger

logger = get_logger(__name__)

CITATION_PATTERN = re.compile(r"\[([^,\]]+),\s*([^\]]+)\]")


@dataclass
class GeneratedDraft:
    text: str
    ungrounded_sentences: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    patterns_used: list[str] = field(default_factory=list)


def generate_draft(
    document_ids: list[str],
    fields_by_doc: dict[str, ExtractedFields],
    chunks: list[RetrievedChunk],
    patterns: list[dict] | None = None,
    base_url: str = "http://localhost:8080/v1",
    model: str = "mistralai/Mistral-Small-3.1-24B-Instruct",
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> GeneratedDraft:
    if not chunks:
        logger.error("No retrievable chunks — aborting generation to prevent hallucination")
        raise ValueError(
            "Zero chunks retrieved above the minimum score threshold. "
            "Cannot generate a grounded draft without evidence."
        )

    patterns = patterns or []
    prompt = build_prompt(fields_by_doc, chunks, patterns)

    client = OpenAI(base_url=base_url, api_key="local")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    draft_text = response.choices[0].message.content.strip()
    ungrounded = _find_ungrounded_sentences(draft_text)
    citations = _extract_citations(draft_text)
    pattern_ids = [p["pattern_id"] for p in patterns if "pattern_id" in p]

    if ungrounded:
        logger.warning(f"{len(ungrounded)} ungrounded sentence(s) detected")

    logger.info(f"Draft generated: {len(draft_text)} chars, {len(citations)} citations, {len(ungrounded)} ungrounded")

    return GeneratedDraft(
        text=draft_text,
        ungrounded_sentences=ungrounded,
        citations=citations,
        patterns_used=pattern_ids,
    )


def _find_ungrounded_sentences(text: str) -> list[str]:
    ungrounded = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("|") or line.startswith("-"):
            continue
        # Skip lines that are structural (headers, tables, list markers)
        if len(line) < 20:
            continue
        if not CITATION_PATTERN.search(line) and "[UNSUPPORTED]" not in line:
            ungrounded.append(line)
    return ungrounded


def _extract_citations(text: str) -> list[dict]:
    citations = []
    for match in CITATION_PATTERN.finditer(text):
        doc_id = match.group(1).strip()
        chunk_id = match.group(2).strip()
        citations.append({
            "document_id": doc_id,
            "chunk_id": chunk_id,
            "draft_char_start": match.start(),
            "draft_char_end": match.end(),
        })
    return citations
