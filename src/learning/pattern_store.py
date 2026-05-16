import uuid
from datetime import datetime, timezone

import psycopg2.extras

from src.utils.db import get_conn as _connect

from src.learning.edit_tracker import ClassifiedEdit
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEDUP_THRESHOLD = 0.2  # normalized edit distance below this = near-duplicate
MIN_FREQUENCY = 3      # patterns below this are stored but not injected into prompts


def _edit_distance_ratio(a: str, b: str) -> float:
    import difflib
    return 1 - difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def upsert_pattern(
    edit: ClassifiedEdit,
    document_type: str | None,
    draft_id: str,
    dsn: str,
    dedup_threshold: float = DEDUP_THRESHOLD,
) -> str:
    with _connect(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT pattern_id, trigger, frequency
                FROM edit_patterns
                WHERE section = %s AND edit_type = %s
                  AND (document_type = %s OR document_type IS NULL)
                """,
                (edit.section, edit.edit_type, document_type),
            )
            existing = cur.fetchall()

            for row in existing:
                if _edit_distance_ratio(edit.trigger, row["trigger"]) < dedup_threshold:
                    cur.execute(
                        """
                        UPDATE edit_patterns
                        SET frequency = frequency + 1,
                            last_seen = %s,
                            source_draft_ids = array_append(source_draft_ids, %s)
                        WHERE pattern_id = %s
                        """,
                        (datetime.now(timezone.utc), draft_id, row["pattern_id"]),
                    )
                    logger.info(f"Incremented frequency for pattern {row['pattern_id']}")
                    return row["pattern_id"]

            pattern_id = f"pat-{uuid.uuid4().hex[:8]}"
            cur.execute(
                """
                INSERT INTO edit_patterns
                    (pattern_id, document_type, section, edit_type, trigger,
                     original_text, corrected_text, frequency, first_seen, last_seen, source_draft_ids)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s)
                """,
                (
                    pattern_id,
                    document_type,
                    edit.section,
                    edit.edit_type,
                    edit.trigger,
                    edit.original_text,
                    edit.corrected_text,
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc),
                    [draft_id],
                ),
            )
            logger.info(f"Inserted new pattern {pattern_id}")
            return pattern_id


def get_patterns(
    document_type: str | None,
    sections: list[str],
    dsn: str,
    limit: int = 5,
    min_frequency: int = MIN_FREQUENCY,
) -> list[dict]:
    with _connect(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM edit_patterns
                WHERE (document_type = %s OR document_type IS NULL)
                  AND section = ANY(%s)
                  AND frequency >= %s
                ORDER BY frequency DESC
                LIMIT %s
                """,
                (document_type, sections, min_frequency, limit),
            )
            return [dict(row) for row in cur.fetchall()]


def delete_pattern(pattern_id: str, dsn: str) -> bool:
    with _connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM edit_patterns WHERE pattern_id = %s", (pattern_id,))
            deleted = cur.rowcount > 0
    if deleted:
        logger.info(f"Deleted pattern {pattern_id}")
    return deleted
