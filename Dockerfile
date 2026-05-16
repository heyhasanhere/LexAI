FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Install CUDA-enabled PyTorch before other deps so sentence-transformers
# picks it up instead of the CPU-only wheel from PyPI.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cu124
RUN pip install --no-cache-dir -r requirements.txt
# Pre-download runtime data so first request does not need outbound internet.
RUN python -c "import nltk; nltk.download('punkt_tab', quiet=True)"
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

COPY . .

RUN mkdir -p data/documents
