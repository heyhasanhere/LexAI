#!/usr/bin/env python3
"""
Reset LexAI to a clean state.

Clears:
  - All rows in chunks, documents, drafts, and edit_patterns (Postgres + pgvector)
  - All files in data/documents/

Usage:
  python scripts/reset.py           # prompts for confirmation
  python scripts/reset.py --yes     # skips confirmation
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DSN = "postgresql://ld:ld@localhost:5432/lexai"
DOCUMENT_DIR = ROOT / "data" / "documents"


def reset_postgres(dsn: str) -> None:
    import psycopg2
    with psycopg2.connect(dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE chunks, drafts, documents, edit_patterns RESTART IDENTITY CASCADE"
            )
    print("  Postgres: chunks, documents, drafts, edit_patterns truncated")


def reset_files(document_dir: Path) -> None:
    if not document_dir.exists():
        print(f"  Files: {document_dir} does not exist, skipping")
        return
    removed = sum(1 for f in document_dir.iterdir() if f.is_file() and not f.unlink())
    print(f"  Files: {removed} file(s) removed from {document_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset LexAI to a clean state")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    print("This will permanently delete all documents, drafts, patterns, and uploaded files.")
    if not args.yes:
        answer = input("Type 'yes' to continue: ").strip().lower()
        if answer != "yes":
            print("Aborted.")
            sys.exit(0)

    print("\nResetting...")
    reset_postgres(DSN)
    reset_files(DOCUMENT_DIR)
    print("\nDone. The app is clean.")


if __name__ == "__main__":
    main()
