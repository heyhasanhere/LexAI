"""
Simulates operator edits against generated drafts to seed the pattern store.
Applies a fixed set of known correction patterns to draft text and submits
the result via the API.

Usage:
    python scripts/simulate_edits.py --api-url http://localhost:8000 --draft-ids draft-abc draft-def
    python scripts/simulate_edits.py --api-url http://localhost:8000 --all
"""
import argparse
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.logger import get_logger

logger = get_logger("simulate_edits")

# Known correction patterns to apply to draft text
EDIT_PATTERNS = [
    {
        "find": r"Recording date: (\w+ \d+, \d{4})",
        "replace_fn": lambda m: f"Recording date: {_to_iso(m.group(1))}",
        "description": "reformat written dates to ISO 8601",
    },
    {
        "find": r"- (Grantor|Grantee): ([A-Z][a-z]+ [A-Z][a-z]+)\n",
        "replace_fn": lambda m: f"- {m.group(1)}: {m.group(2)} (verify entity type) \n",
        "description": "flag individual names that may be trust entities",
    },
]

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _to_iso(date_str: str) -> str:
    parts = date_str.replace(",", "").split()
    if len(parts) == 3:
        month = MONTHS.get(parts[0].lower(), "00")
        return f"{parts[2]}-{month}-{parts[1].zfill(2)}"
    return date_str


def apply_edits(draft_text: str) -> str:
    edited = draft_text
    for pattern in EDIT_PATTERNS:
        edited = re.sub(pattern["find"], pattern["replace_fn"], edited)
    return edited


def simulate_for_draft(draft_id: str, api_url: str) -> bool:
    resp = requests.get(f"{api_url}/drafts/{draft_id}")
    if resp.status_code != 200:
        logger.error(f"Could not fetch draft {draft_id}: {resp.status_code}")
        return False

    draft = resp.json()
    if draft["status"] == "submitted":
        logger.info(f"Draft {draft_id} already submitted, skipping")
        return False

    edited_text = apply_edits(draft["draft_text"])

    resp = requests.post(
        f"{api_url}/drafts/{draft_id}/submit",
        json={"submitted_text": edited_text},
    )
    if resp.status_code != 200:
        logger.error(f"Submit failed for {draft_id}: {resp.text}")
        return False

    result = resp.json()
    logger.info(f"Draft {draft_id}: {result['patterns_extracted']} pattern(s) extracted")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate operator edits to seed pattern store")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--draft-ids", nargs="+", default=[])
    parser.add_argument("--all", action="store_true", help="Fetch and edit all unsubmitted drafts")
    args = parser.parse_args()

    draft_ids = args.draft_ids

    if args.all:
        resp = requests.get(f"{args.api_url}/drafts", params={"status": "generated", "limit": 100})
        if resp.status_code != 200:
            logger.error(f"Could not list drafts: {resp.text}")
            sys.exit(1)
        draft_ids = [d["draft_id"] for d in resp.json()["drafts"]]

    if not draft_ids:
        logger.warning("No draft IDs specified. Use --draft-ids or --all.")
        return

    logger.info(f"Simulating edits for {len(draft_ids)} draft(s)")
    succeeded = sum(simulate_for_draft(did, args.api_url) for did in draft_ids)
    logger.info(f"Done: {succeeded}/{len(draft_ids)} drafts processed")


if __name__ == "__main__":
    main()
