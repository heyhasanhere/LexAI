"""
Bulk ingestion CLI. Processes all supported files in a directory.

Usage:
    python scripts/ingest_batch.py --input-dir sample_data/inputs/cuad/
    python scripts/ingest_batch.py --input-dir sample_data/inputs/ --recursive
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extraction.chunker import chunk_document
from src.extraction.field_extractor import extract_fields
from src.ingestion.loader import load_document, SUPPORTED_MIME_TYPES
from src.retrieval.vector_store import upsert_chunks
from src.utils.logger import get_logger
from src.utils.storage import create_document, init_db, update_document

import mimetypes

logger = get_logger("ingest_batch")

DSN = "postgresql://ld:ld@localhost:5432/lexai"
LLM_BASE_URL = "http://localhost:8080/v1"
LLM_MODEL = "Qwen/Qwen3-4B-AWQ"
EMBED_DEVICE = "cuda"

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".txt"}


def ingest_file(path: Path) -> str | None:
    mime, _ = mimetypes.guess_type(str(path))
    if mime not in SUPPORTED_MIME_TYPES:
        logger.warning(f"Skipping unsupported file: {path.name}")
        return None

    document_id = create_document(path.name, _file_type(path), DSN)
    logger.info(f"Ingesting {path.name} → {document_id}")

    try:
        update_document(document_id, "processing", DSN)
        loaded = load_document(path)

        fields = extract_fields(loaded.page_annotated_text, base_url=LLM_BASE_URL, model=LLM_MODEL)
        pages = [(p.page_number, p.text, p.ocr_confidence) for p in loaded.pages]
        chunks = chunk_document(document_id, pages)
        upsert_chunks(chunks, device=EMBED_DEVICE, dsn=DSN)

        update_document(
            document_id,
            "ready",
            DSN,
            page_count=loaded.page_count,
            fields_json=fields.to_dict(),
            flags=loaded.flags + fields.flags,
        )
        logger.info(f"{path.name}: {loaded.page_count} pages, {len(chunks)} chunks → ready")
        return document_id

    except Exception as e:
        logger.error(f"{path.name} failed: {e}")
        update_document(document_id, "failed", DSN, error_detail=str(e))
        return None


def _file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}:
        return "image"
    return "text"


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch ingest documents into LexAI")
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--recursive", action="store_true")
    args = parser.parse_args()

    init_db(DSN)

    pattern = "**/*" if args.recursive else "*"
    files = [
        f for f in args.input_dir.glob(pattern)
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not files:
        logger.warning(f"No supported files found in {args.input_dir}")
        return

    logger.info(f"Found {len(files)} file(s) to ingest")
    succeeded, failed = 0, 0

    for path in sorted(files):
        doc_id = ingest_file(path)
        if doc_id:
            succeeded += 1
        else:
            failed += 1

    logger.info(f"Ingestion complete: {succeeded} succeeded, {failed} failed")


if __name__ == "__main__":
    main()
