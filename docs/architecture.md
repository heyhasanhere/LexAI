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

## Technology Choices

| Component | Choice | Reason |
|---|---|---|
| OCR | Tesseract | Runs locally, no data egress; cloud vision providers pluggable via config |
| PDF text extraction | pdfminer.six | Extracts text layer directly; falls back to OCR per-page if text layer is absent |
| PDF rendering | pdf2image + Poppler | Renders scanned pages to images for OCR at configurable DPI |
| Vector store | ChromaDB | Runs in a single Docker container, zero external dependencies for dev |
| LLM | Mistral-Small-3.1-24B-Instruct via vLLM | Runs fully local at bfloat16 with tensor-parallel-size 2; strong structured JSON output and instruction-following; vLLM exposes an OpenAI-compatible API so no custom client code needed |
| Embedding | BAAI/bge-large-en-v1.5 via sentence-transformers | Best quality local English embedding model; 335M params, no API cost |
| Edit pattern store | Postgres | Structured queries by `(document_type, section, edit_type)` are simpler and more auditable than vector retrieval for this use case |
| API | FastAPI | Async-ready, automatic OpenAPI schema generation, native Pydantic integration |
| Validation | Pydantic v2 | Covers both LLM output validation and API schemas |
