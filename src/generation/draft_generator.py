import re
from dataclasses import dataclass, field

from src.extraction.field_extractor import ExtractedFields
from src.generation.prompts import build_prompt
from src.retrieval.vector_store import RetrievedChunk
from src.utils.llm_client import chat_extra_body, get_client
from src.utils.logger import get_logger

logger = get_logger(__name__)

CITATION_PATTERN = re.compile(r"\[(doc-[a-f0-9]+),\s*(doc-[a-f0-9]+-chunk-\d+)\]")
PAGE_REF_PATTERN = re.compile(r"\[p\.\d+\]")


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
    model: str = "Qwen/Qwen3-4B-AWQ",
    api_key: str = "local",
    provider: str = "vllm",
    temperature: float = 0.1,
    max_tokens: int = 2000,
    doc_meta: dict[str, dict] | None = None,
) -> GeneratedDraft:
    if not chunks:
        logger.error("No retrievable chunks — aborting generation to prevent hallucination")
        raise ValueError(
            "Zero chunks retrieved above the minimum score threshold. "
            "Cannot generate a grounded draft without evidence."
        )

    patterns = patterns or []
    prompt = build_prompt(fields_by_doc, chunks, patterns, doc_meta=doc_meta)

    client = get_client(provider, base_url, api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=chat_extra_body(provider),
    )

    draft_text = response.choices[0].message.content.strip()
    if "<think>" in draft_text:
        draft_text = draft_text.split("</think>")[-1].strip()
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
        if not line:
            continue
        if line.startswith("#") or line.startswith("|") or line.startswith("─") or line.startswith("━"):
            continue
        if len(line) < 20:
            continue
        # Skip ALL CAPS section headers and format-hint lines
        if line.isupper() or line.startswith("Overall:") or line.startswith("TYPE:") or line.startswith("DOCUMENT:"):
            continue
        has_citation = CITATION_PATTERN.search(line)
        has_page_ref = PAGE_REF_PATTERN.search(line)
        has_flag = "[NOT FOUND]" in line
        if not has_citation and not has_page_ref and not has_flag:
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
