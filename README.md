# LegalDraft — Legal Document Ingestion and Draft Generation System

An internal workflow that ingests messy legal documents, extracts structured information, retrieves relevant evidence, and generates grounded draft outputs that operators can edit and improve over time.

## What This System Does

1. **Ingests** PDFs, scanned images, and handwritten notes — including low-quality, partially illegible sources
2. **Extracts** raw text via OCR and structures it into typed fields (parties, dates, amounts, case numbers, etc.)
3. **Retrieves** relevant evidence chunks from ingested documents using vector search
4. **Generates** a grounded *Case Fact Summary* — a first-pass internal memo anchored to specific evidence spans
5. **Learns** from operator edits: tracks how the default draft was changed and uses those patterns to improve future generations

The system does not generate text unsupported by source documents. Every claim in the output is linked back to a source span.

---

## Architecture Overview

See [docs/architecture.md](docs/architecture.md) for the full diagram and technology choices.

```
Raw Documents
     │
     ▼
[Ingestion & OCR Layer]     ← handles PDFs, images, handwritten scans
     │
     ▼
[Extraction Layer]          ← structured fields + cleaned text chunks
     │
     ├──► [Vector Store]    ← chunked embeddings for retrieval
     │
     ▼
[Retrieval Layer]           ← query-time semantic search over chunks
     │
     ▼
[Draft Generation]          ← LLM call with retrieved context only
     │
     ▼
[Operator Review / API]     ← edits captured with before/after diff
     │
     ▼
[Edit Learning Store]       ← patterns extracted and applied to future prompts
```

---

## Directory Structure

```
legaldraft/
├── README.md
├── docs/
│   ├── architecture.md          # component diagram + technology choices
│   ├── data_model.md            # entity designs for document, chunk, draft, edit
│   └── improvement_loop.md      # design for how operator edits feed back into the system
├── config/
│   └── settings.yaml            # all runtime configuration
├── src/
│   ├── ingestion/               # file loading, OCR, PDF extraction
│   ├── extraction/              # chunking, structured field extraction
│   ├── retrieval/               # embedding, vector store
│   ├── generation/              # draft generation, prompts
│   ├── learning/                # edit tracking, pattern store
│   ├── api/                     # FastAPI routes and schemas
│   └── utils/                   # logging, storage helpers
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── sample_data/
│   ├── inputs/                  # real documents from RVL-CDIP and CUAD
│   └── outputs/                 # drafts generated at runtime
├── scripts/
│   ├── ingest_batch.py          # CLI for bulk ingestion
│   └── simulate_edits.py        # generates synthetic operator edits for dev
├── pyproject.toml
├── requirements.txt
└── docker-compose.yml
```

---

## Prerequisites

- Python 3.11+
- Docker and Docker Compose
- NVIDIA Container Toolkit — required for vLLM GPU access in Docker ([install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html))
- Tesseract OCR — `sudo apt install tesseract-ocr`
- Poppler utils — `sudo apt install poppler-utils`
- A Hugging Face account with access to `mistralai/Mistral-Small-3.1-24B-Instruct` (free, requires accepting the model license)
- `HF_TOKEN` environment variable set to your Hugging Face token (for model download on first run)

---

## Setup

```bash
git clone <repo-url>
cd legaldraft
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set your Hugging Face token (needed for first-time model download):

```bash
export HF_TOKEN=hf_...
```

Start backing services (ChromaDB, Postgres, and vLLM):

```bash
docker-compose up -d
```

vLLM will download Mistral-Small-3.1-24B on first start (~15GB). Subsequent starts load from the Docker volume cache.

---

## Sample Data

Two public datasets are used as inputs. See [sample_data/inputs/README.md](sample_data/inputs/README.md) for details.

- **RVL-CDIP** (`sample_data/inputs/rvl_cdip/`) — 50 real scanned document images (forms, handwritten, letters, memos, invoices)
- **CUAD** (`sample_data/inputs/cuad/`) — 10 real commercial legal contracts from SEC EDGAR filings
