# Architecture

## System Overview

LexAI is a pipeline system. Each stage has a single responsibility and a defined input/output boundary, so components can be swapped independently. The pipeline is synchronous for v1.

---

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Operator / API Client                      │
└───────────┬─────────────────────────────────┬───────────────────────┘
            │ upload document                 │ request draft
            ▼                                 ▼
┌───────────────────────┐         ┌───────────────────────────────────┐
│   Ingestion Layer     │         │            API Layer              │
│                       │         │         (FastAPI)                 │
│  - file type detect   │         └──────────────┬────────────────────┘
│  - PDF text extract   │                        │
│  - OCR pipeline       │                        ▼
│                       │         ┌───────────────────────────────────┐
│  Output:              │         │        Retrieval Layer            │
│  - raw text per page  │──────►  │                                   │
│  - OCR confidence     │         │  - embed query                    │
└───────────────────────┘         │  - search vector store            │
            │                     │  - filter + rank chunks           │
            ▼                     └──────────────┬────────────────────┘
┌───────────────────────┐                        │
│   Extraction Layer    │                        ▼
│                       │         ┌───────────────────────────────────┐
│  - sentence chunking  │──────►  │       Generation Layer            │
│  - embed + index      │  Vector │                                   │
│  - LLM field extract  │  Store  │  - retrieved chunks + fields      │
│                       │         │  - edit patterns (few-shot)       │
│  Output:              │────────►│  - LLM call (temp 0.1)            │
│  - typed chunks       │  fields │  - grounding verifier             │
│  - structured fields  │         │                                   │
└───────────────────────┘         │  Output: draft + citations        │
                                  └──────────────┬────────────────────┘
                                                 │
                                                 ▼
                                  ┌───────────────────────────────────┐
                                  │       Operator Review             │
                                  │  reads draft, submits edits       │
                                  └──────────────┬────────────────────┘
                                                 │
                                                 ▼
                                  ┌───────────────────────────────────┐
                                  │      Edit Learning Layer          │
                                  │                                   │
                                  │  - diff original vs submitted     │
                                  │  - classify edits via LLM         │
                                  │  - store reusable patterns        │
                                  │  - inject into future prompts     │
                                  └───────────────────────────────────┘
```

---

## Large Document Extraction

Field extraction (`src/extraction/field_extractor.py`) uses a multi-turn chunking strategy to handle documents that exceed the LLM's context window:

1. `load_document` produces page-annotated text with `[PAGE N]` markers at each page boundary.
2. `extract_fields` calls `_split_into_page_chunks` which splits on `[PAGE N]` boundaries into chunks of at most `max_chunk_chars` (default 40,000 characters, ≈ 10,000 tokens).
3. One LLM call is made per chunk. Each call receives the same extraction prompt and returns a partial `ExtractedFields` JSON.
4. `_merge_fields` combines all partial results:
   - All list fields (parties, key\_dates, key\_clauses, etc.) are concatenated across chunks.
   - `risk_summary` escalates to the highest severity level seen; all risk items are pooled.
   - `document_type` uses the first non-null value.
   - `flags` are deduplicated.

**Token budget per chunk** (with `--max-model-len 16384`):

```
prompt template:  ~700 tokens
document chunk:  ~10,000 tokens  (40,000 chars ÷ 4 chars/token)
LLM response:     4,096 tokens
─────────────────────────────
total:           ~14,796 tokens  <  16,384 ✓
```

---

## Technology Choices

| Component | Choice | Reason |
|---|---|---|
| OCR | Tesseract | Runs locally, no data egress; cloud vision providers pluggable via config |
| PDF text extraction | pdfminer.six | Extracts text layer directly; falls back to OCR per-page if text layer is absent |
| PDF rendering | pdf2image + Poppler | Renders scanned pages to images for OCR at configurable DPI |
| Vector store | ChromaDB | Runs in a single Docker container, zero external dependencies for dev |
| LLM | Qwen/Qwen3-14B-AWQ via vLLM | Runs fully local with AWQ 4-bit quantization (~7.7 GB weights) across 2× RTX 3060 with tensor-parallel-size 2; chain-of-thought mode disabled via `enable_thinking: false`; vLLM exposes an OpenAI-compatible API so no custom client code needed |
| Embedding | BAAI/bge-large-en-v1.5 via sentence-transformers | Best quality local English embedding model; 335M params (~1.34 GB), runs on `cuda:1`; no API cost |
| Edit pattern store | Postgres | Structured queries by `(document_type, section, edit_type)` are simpler and more auditable than vector retrieval for this use case |
| API | FastAPI | Async-ready, automatic OpenAPI schema generation, native Pydantic integration |
| Validation | Pydantic v2 | Covers both LLM output validation and API schemas |
