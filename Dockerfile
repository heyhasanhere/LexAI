FROM python:3.12-slim

# libpq-dev + gcc: psycopg2-binary compilation
# libgl1: required by surya-ocr (Marker's OCR backend) via OpenCV
# curl: Docker healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    libgl1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Install CUDA-enabled PyTorch before other deps so Marker + sentence-transformers
# pick it up instead of the CPU-only wheel from PyPI.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu124
RUN pip install --no-cache-dir -r requirements.txt
# Pre-download runtime data so first request does not need outbound internet.
RUN python -c "import nltk; nltk.download('punkt_tab', quiet=True)"
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
# Marker models (~2-4 GB) are downloaded on first use and cached via the
# huggingface_cache volume — no pre-download here to keep image size small.

COPY . .

RUN mkdir -p data/documents
