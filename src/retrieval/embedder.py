from functools import lru_cache

from sentence_transformers import SentenceTransformer

from src.utils.logger import get_logger

logger = get_logger(__name__)

MODEL_NAME = "BAAI/bge-large-en-v1.5"


@lru_cache(maxsize=1)
def _get_model(device: str = "cuda") -> SentenceTransformer:
    logger.info(f"Loading embedding model {MODEL_NAME} on {device}")
    return SentenceTransformer(MODEL_NAME, device=device)


def embed(texts: list[str], device: str = "cuda", batch_size: int = 64) -> list[list[float]]:
    if not texts:
        return []
    model = _get_model(device)
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vectors.tolist()
