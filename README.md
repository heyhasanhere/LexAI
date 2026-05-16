# LexAI — Legal Document Analysis Platform

<!-- live-demo --> **[▶ Open Live Demo](https://developments-changes-backgrounds-lock.trycloudflare.com)**

LexAI ingests legal documents, extracts structured fields via LLM, retrieves relevant precedents from a vector store, generates grounded draft summaries with inline citations, and learns from operator edits to improve future drafts.

---

## 1. Installation

<details>
<summary><strong>Use LexAI from a browser</strong></summary>

<br>

If the operator is running `scripts/serve.sh`, they will share a URL that looks like:

```
https://some-random-words.trycloudflare.com
```

Open it in any browser. No account, no install, no Docker.

</details>

---

<details>
<summary><strong>Install LexAI locally</strong></summary>

<br>

```bash
curl -fsSL https://raw.githubusercontent.com/heyhasanhere/LexAI/main/install.sh | bash
```

The script asks you to choose an LLM backend (see [LLM backend](#5-llm-backend)), then:

- Installs Docker and git if they are missing
- Clones the repo into `~/lexai`
- Writes a `.env` file with your choices
- Builds the application Docker image
- Starts all services with `docker compose up -d`
- Prints the local URLs when the API becomes healthy

After installation:

| Service | URL |
|---|---|
| Streamlit UI | http://localhost:8501 |
| FastAPI (REST) | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |

To stop: `docker compose --project-directory ~/lexai down`  
To restart: `docker compose --project-directory ~/lexai up -d`

<details>
<summary><strong>Self-host LexAI (expose your own GPU)</strong></summary>

<br>

#### Prerequisites

| Requirement | Notes |
|---|---|
| Linux host | Ubuntu 22.04+ recommended. **macOS is not supported for the `full` profile** — Docker on macOS does not support NVIDIA GPU passthrough. |
| NVIDIA GPU(s) | 24 GB VRAM total minimum for Qwen3-14B-AWQ |
| NVIDIA drivers | Run `nvidia-smi` to verify |
| A domain name | Point an A record at your server's IP (used for a stable URL in `install.sh`) |

#### Step 1 — First-time host setup

```bash
bash scripts/setup_host.sh
```

Installs Docker Engine, the NVIDIA Container Toolkit, and required system packages. Reboot if prompted.

#### Step 2 — Clone and configure

```bash
git clone https://github.com/heyhasanhere/LexAI.git ~/lexai
cd ~/lexai
cp .env.example .env
```

Edit `.env` and set:

```env
COMPOSE_PROFILES=full
LD_LLM__BASE_URL=http://vllm:8000/v1
LD_LLM__MODEL=Qwen/Qwen3-14B-AWQ
LD_LLM__API_KEY=local
HF_TOKEN=          # optional — speeds up model download from HuggingFace
```

#### Step 3 — Start all services

```bash
docker compose up -d
```

This starts: Postgres (with pgvector), vLLM (loads the model into GPU memory), nginx gateway, FastAPI, and Streamlit.

First start takes 5–15 minutes while vLLM downloads and loads the model. Monitor with:

```bash
docker compose logs -f vllm
```

Wait until you see `Application startup complete` in the vLLM logs. Verify health:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

#### Step 4 — Expose publicly via Cloudflare Quick Tunnels

```bash
bash scripts/serve.sh
```

The script verifies that the UI (port 8501) and nginx gateway are running, then starts two outbound Cloudflare tunnels. When both are ready, it prints:

```
════════════════════════════════════════════
  BROWSER URL  →  https://abc-def-ghi.trycloudflare.com
  Share this link — users open LexAI here
════════════════════════════════════════════

════════════════════════════════════════════
  GPU API URL  →  https://xyz-uvw-rst.trycloudflare.com/v1
  Paste into install.sh as LEXAI_REMOTE_URL
════════════════════════════════════════════
```

**BROWSER URL** — share with users who want to use LexAI in a browser without installing anything.

**GPU API URL** — paste this into `install.sh` as the value of `LEXAI_REMOTE_URL` so that users who install locally can point at your GPU as their LLM backend.

Press `Ctrl-C` to stop both tunnels.

> **Note:** Quick Tunnel URLs are randomly generated and change each time `serve.sh` is run. For a stable permanent URL, set up a named Cloudflare Tunnel attached to your domain — see the [Cloudflare Tunnel docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/).

</details>

</details>

---

## 2. Architecture

```
Browser
  │
  ▼
Streamlit UI (port 8501)
  │  HTTP (internal Docker network)
  ▼
FastAPI (port 8000)
  ├── Postgres + pgvector — documents, drafts, edit_patterns, chunk embeddings (BGE-large-en-v1.5)
  └── LLM backend
        ├── OpenAI API          (lite profile, option 1)
        ├── Remote vLLM         (lite profile, option 2 — via Cloudflare tunnel)
        └── Local vLLM          (full profile, option 3 — internal Docker network)

Public access (operator only, full profile):
  Cloudflare edge
    ├──→ Quick Tunnel :8501  →  Streamlit        (users browse here)
    └──→ Quick Tunnel       →  nginx gateway  →  vLLM
```

### Data flows

**Document ingestion** (`POST /documents`)  
File → MIME detection → PyMuPDF (native PDFs) or Marker OCR (scanned/image) or HTML tag stripping → page-annotated text → LLM field extraction → sentence chunking with overlap → BGE embedding → pgvector upsert + Postgres row.

**Draft generation** (`POST /drafts`)  
Semantic queries → pgvector top-k retrieval → load generalizable edit patterns from Postgres (filtered by document type and section) → build prompt with extracted fields, retrieved chunks, and prior edit patterns → LLM call → citation parsing → ungrounded sentence detection → return draft. Generation aborts with an error if zero chunks are retrieved (intentional hallucination prevention).

**Edit learning** (`POST /drafts/{id}/submit`)  
Operator submits corrected draft text → difflib line-level diff against original → LLM classifies each changed hunk (edit type, when to apply, whether generalizable) → only edits marked `generalizable=true` stored in the `edit_patterns` Postgres table → patterns that meet the frequency threshold are injected as few-shot examples into future generation prompts.

---

## 3. Development Setup

```bash
# Install system dependencies (Ubuntu)
sudo apt-get install -y libpq-dev libgl1

# Create virtualenv and install Python dependencies
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start only the backing services
docker compose up -d postgres
# To include local GPU inference:
# COMPOSE_PROFILES=full docker compose up -d postgres vllm gateway

# Start API with auto-reload
uvicorn src.api.routes:app --host 0.0.0.0 --port 8000 --reload

# Start UI (in a second terminal)
streamlit run src/ui/app.py

# Run tests
pytest

# Batch ingest test documents
python scripts/ingest_batch.py

# Generate synthetic operator edits (for testing the edit learning pipeline)
python scripts/simulate_edits.py

# Reset all data — drops and recreates Postgres tables, clears ChromaDB
python scripts/reset.py
```

---

## 4. More about installations

<details>
<summary><strong>How install.sh works internally</strong></summary>

<br>

```
curl -fsSL .../install.sh | bash
```

**Step 1 — OS detection**  
Reads `/etc/os-release` to identify the Linux distribution (ubuntu, fedora, arch, etc.) or detects macOS. Used to choose the correct package manager in subsequent steps.

**Step 2 — Install git**  
Calls `apt-get`, `dnf`, or `pacman` depending on distro. Skipped if `git` is already on `$PATH`.

**Step 3 — Install Docker**  
Same distro-aware logic. Adds the official Docker apt/dnf repo, installs `docker-ce` + `docker-compose-plugin`, enables the daemon, and adds the current user to the `docker` group. Skipped if Docker is already installed.

**Step 4 — Clone or update repo**  
Clones `https://github.com/heyhasanhere/LexAI.git` into `~/lexai` (or `$LEXAI_DIR` if set). If the directory already exists, runs `git pull --ff-only` instead.

**Step 5 — Choose LLM backend (interactive)**  
Prompts for one of three options (see [LLM backend](#5-llm-backend)). Sets four variables: `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `COMPOSE_PROFILES`.

**Step 6 — Write .env**  
Creates `~/lexai/.env` from the variables set in step 5. This file is read by `docker compose` and by the FastAPI application at startup. It contains the LLM endpoint, model name, and API key.

**Step 7 — Build application image**  
Runs `docker compose build api`. Builds a single `lexai-app` image used by both the `api` and `ui` services. Installs Python dependencies, Tesseract OCR, poppler, and libpq. Takes approximately 3 minutes on first run; cached on subsequent runs.

**Step 8 — Start services**  
Runs `docker compose up -d`. Which services start depends on `COMPOSE_PROFILES`:

- `lite` — Postgres (with pgvector), FastAPI, Streamlit (no local GPU)
- `full` — everything above plus vLLM and the nginx rate-limiting gateway

**Step 9 — Health check**  
Polls `http://localhost:8000/health` every 5 seconds for up to 150 seconds. Prints the local URLs once the API responds with `{"status":"ok"}`.

</details>

<details>
<summary><strong>How serve.sh works internally</strong></summary>

<br>

```bash
bash scripts/serve.sh
```

**Step 1 — Verify services are running**  
Sends a test HTTP request to port 8501 (Streamlit) and checks that the nginx gateway returns the expected response on `/`. Exits with an error message if either is unreachable.

**Step 2 — Install cloudflared**  
Checks for `cloudflared` on `$PATH`. If missing, downloads the appropriate package from the GitHub releases page and installs it. On macOS, uses `brew`.

**Step 3 — Start UI tunnel**  
Runs `cloudflared tunnel --url http://localhost:8501` as a background process. The tunnel is entirely outbound — cloudflared opens a persistent HTTPS connection to Cloudflare's edge network, which routes incoming browser requests back to port 8501 on this machine. No firewall rules, no port forwarding, no static IP required.

**Step 4 — Start GPU gateway tunnel**  
Same mechanism for the nginx gateway port. This port is bound only to `127.0.0.1` in Docker, so it cannot be reached directly from the internet — only through the tunnel. The tunnel forwards requests to nginx, which enforces rate limits before proxying to vLLM.

**Step 5 — Print URLs and wait**  
Each tunnel process pipes its stderr through `parse_tunnel`, which watches for the `*.trycloudflare.com` URL and prints the highlighted banner when it appears. Both processes run until `Ctrl-C`, which kills both via a `trap INT TERM` handler.

</details>

---

## 5. LLM backend

### Option 1 — OpenAI API

Uses your own OpenAI account. Default model: `gpt-4o-mini`.

- Requires an `sk-...` API key
- No GPU required on the host
- `COMPOSE_PROFILES=lite` — vLLM is not started
- Cost: billed per token by OpenAI

### Option 2 — LexAI remote GPU (free)

Sends requests to the operator's vLLM endpoint (Qwen3-14B-AWQ). No key required.

- Rate-limited per IP by the nginx gateway
- `COMPOSE_PROFILES=lite` — no local GPU needed
- The operator must be running `scripts/serve.sh` for this to work

### Option 3 — Local GPU

Runs Qwen3-14B-AWQ on your own NVIDIA GPU(s).

- Requires NVIDIA drivers and 24 GB VRAM minimum
- `COMPOSE_PROFILES=full`
- vLLM downloads the model (~8 GB) on first start
- No external network dependency after download

---

## 6. Abuse Protection

The public GPU endpoint is protected at multiple layers:

| Layer | Mechanism | Effect |
|---|---|---|
| vLLM | Concurrency limit | Excess requests queue rather than crash the service |
| nginx | Rate limiting per IP | Returns 429 on excess requests |
| nginx | Payload size limit | Rejects oversized payloads |
| nginx | Endpoint allowlist | Only `/v1/chat/completions` is proxied; all other paths return 403 |
| nginx | Auth header stripping | Strips client-supplied auth headers before proxying |
| nginx | Real IP detection | Rate limiting uses the real client IP via Cloudflare headers |
| Cloudflare | DDoS protection, TLS termination | Absorbs volumetric attacks before they reach the host |

---

## 7. Configuration reference

Config is loaded from `config/settings.yaml`. Any key can be overridden with an environment variable using the prefix `LD_` and double-underscore nesting (e.g. `LD_LLM__BASE_URL` overrides `llm.base_url`).

| Env var | settings.yaml key | Default | Purpose |
|---|---|---|---|
| `LD_LLM__BASE_URL` | `llm.base_url` | `http://localhost:8080/v1` | LLM API endpoint |
| `LD_LLM__MODEL` | `llm.model` | `Qwen/Qwen3-14B-AWQ` | Model name sent in API requests |
| `LD_LLM__API_KEY` | `llm.api_key` | `local` | API key (`sk-...` for OpenAI) |
| `LD_LLM__MAX_TOKENS` | `llm.max_tokens` | `4096` | Max tokens in LLM responses |
| `LD_STORAGE__POSTGRES_DSN` | `storage.postgres_dsn` | *(set in .env)* | Postgres connection string (pgvector is in the same DB) |
| `LD_EMBEDDING__MODEL` | `embedding.model` | `BAAI/bge-large-en-v1.5` | Sentence-transformers model |
| `LD_EMBEDDING__DEVICE` | `embedding.device` | `auto` | `auto`, `cpu`, or `cuda:N`. `auto` picks the GPU with the most free VRAM if CUDA is available, else CPU. |

> **Embedding device:** Default is `auto`. When CUDA is available the model (BGE-large-en-v1.5, ~670 MiB in float16) is loaded on the GPU with the most free VRAM. Force CPU with `LD_EMBEDDING__DEVICE=cpu`.
