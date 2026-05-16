from dataclasses import dataclass

import numpy as np
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector

from src.extraction.chunker import Chunk
from src.retrieval.embedder import embed
from src.utils.logger import get_logger

logger = get_logger(__name__)

EMBED_DIM = 1024  # BAAI/bge-large-en-v1.5 output dimension


def _conn(dsn: str):
    conn = psycopg2.connect(dsn)
    register_vector(conn)
    return conn


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    page_number: int
    text: str
    ocr_confidence: float
    score: float
    query: str


def upsert_chunks(
    chunks: list[Chunk],
    device: str = "cuda",
    batch_size: int = 64,
    dsn: str = "postgresql://ld:ld@localhost:5432/lexai",
) -> None:
    if not chunks:
        return

    texts = [c.text for c in chunks]
    vectors = embed(texts, device=device, batch_size=batch_size)

    with _conn(dsn) as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO chunks
                    (chunk_id, document_id, page_number, chunk_index,
                     char_start, char_end, ocr_confidence, token_count, text, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    text = EXCLUDED.text,
                    embedding = EXCLUDED.embedding
                """,
                [
                    (
                        c.chunk_id, c.document_id, c.page_number, c.chunk_index,
                        c.char_start, c.char_end, c.ocr_confidence, c.token_count,
                        c.text, np.array(v, dtype=np.float32),
                    )
                    for c, v in zip(chunks, vectors)
                ],
            )
    logger.info(f"Upserted {len(chunks)} chunks into pgvector")


def delete_by_document(
    document_id: str,
    dsn: str = "postgresql://ld:ld@localhost:5432/lexai",
) -> int:
    with _conn(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            count = cur.rowcount
    logger.info(f"Deleted {count} chunk(s) for document {document_id}")
    return count


def query(
    queries: list[str],
    document_ids: list[str],
    top_k: int = 8,
    min_score: float = 0.35,
    device: str = "cuda",
    dsn: str = "postgresql://ld:ld@localhost:5432/lexai",
    **_ignored,
) -> list[RetrievedChunk]:
    query_vectors = embed(queries, device=device, batch_size=len(queries))

    seen: set[str] = set()
    retrieved: list[RetrievedChunk] = []

    with _conn(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for query_text, qvec in zip(queries, query_vectors):
                qvec_np = np.array(qvec, dtype=np.float32)
                cur.execute(
                    """
                    SELECT chunk_id, document_id, page_number, text, ocr_confidence,
                           1 - (embedding <=> %s) AS score
                    FROM chunks
                    WHERE document_id = ANY(%s)
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    (qvec_np, document_ids, qvec_np, top_k * 2),
                )
                for row in cur.fetchall():
                    score = float(row["score"])
                    cid = row["chunk_id"]
                    if score < min_score or cid in seen:
                        continue
                    seen.add(cid)
                    retrieved.append(RetrievedChunk(
                        chunk_id=cid,
                        document_id=row["document_id"],
                        page_number=row["page_number"],
                        text=row["text"],
                        ocr_confidence=row["ocr_confidence"],
                        score=score,
                        query=query_text,
                    ))

    retrieved.sort(key=lambda r: r.score, reverse=True)
    logger.info(f"Retrieved {len(retrieved)} chunks for {len(queries)} queries")
    return retrieved[:top_k]
