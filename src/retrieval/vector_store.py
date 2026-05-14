from dataclasses import dataclass

import chromadb
from chromadb.config import Settings

from src.extraction.chunker import Chunk
from src.retrieval.embedder import embed
from src.utils.logger import get_logger

logger = get_logger(__name__)

COLLECTION_NAME = "lexai_chunks"


def _get_client(host: str = "localhost", port: int = 8001) -> chromadb.HttpClient:
    return chromadb.HttpClient(
        host=host,
        port=port,
        settings=Settings(anonymized_telemetry=False),
    )


def _get_collection(client: chromadb.HttpClient) -> chromadb.Collection:
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


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
    host: str = "localhost",
    port: int = 8001,
) -> None:
    if not chunks:
        return

    client = _get_client(host, port)
    collection = _get_collection(client)

    texts = [c.text for c in chunks]
    vectors = embed(texts, device=device, batch_size=batch_size)

    collection.upsert(
        ids=[c.chunk_id for c in chunks],
        embeddings=vectors,
        documents=texts,
        metadatas=[
            {
                "document_id": c.document_id,
                "page_number": c.page_number,
                "chunk_index": c.chunk_index,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "ocr_confidence": c.ocr_confidence,
                "token_count": c.token_count,
            }
            for c in chunks
        ],
    )
    logger.info(f"Upserted {len(chunks)} chunks into vector store")


def query(
    queries: list[str],
    document_ids: list[str],
    top_k: int = 8,
    min_score: float = 0.35,
    device: str = "cuda",
    host: str = "localhost",
    port: int = 8001,
) -> list[RetrievedChunk]:
    client = _get_client(host, port)
    collection = _get_collection(client)

    query_vectors = embed(queries, device=device, batch_size=len(queries))

    results = collection.query(
        query_embeddings=query_vectors,
        n_results=top_k,
        where={"document_id": {"$in": document_ids}},
        include=["documents", "metadatas", "distances"],
    )

    seen: set[str] = set()
    retrieved: list[RetrievedChunk] = []

    for q_idx, query_text in enumerate(queries):
        ids = results["ids"][q_idx]
        docs = results["documents"][q_idx]
        metas = results["metadatas"][q_idx]
        distances = results["distances"][q_idx]

        for chunk_id, doc, meta, dist in zip(ids, docs, metas, distances):
            # Chroma cosine distance: 0 = identical, 2 = opposite. Convert to similarity.
            score = 1 - (dist / 2)
            if score < min_score or chunk_id in seen:
                continue
            seen.add(chunk_id)
            retrieved.append(RetrievedChunk(
                chunk_id=chunk_id,
                document_id=meta["document_id"],
                page_number=meta["page_number"],
                text=doc,
                ocr_confidence=meta["ocr_confidence"],
                score=score,
                query=query_text,
            ))

    retrieved.sort(key=lambda r: r.score, reverse=True)
    logger.info(f"Retrieved {len(retrieved)} chunks for {len(queries)} queries")
    return retrieved[:top_k]
