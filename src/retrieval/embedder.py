from functools import lru_cache

import torch
from sentence_transformers import SentenceTransformer

from src.utils.logger import get_logger

logger = get_logger(__name__)

MODEL_NAME = "BAAI/bge-large-en-v1.5"


def _resolve_device(device: str) -> str:
    if device == "auto":
        if not torch.cuda.is_available():
            return "cpu"
        # Prefer the GPU with the most free VRAM to avoid contention with vLLM
        best = max(range(torch.cuda.device_count()),
                   key=lambda i: torch.cuda.mem_get_info(i)[0])
        return f"cuda:{best}"
    return device


@lru_cache(maxsize=1)
def _get_model(device: str = "cuda") -> SentenceTransformer:
    logger.info(f"Loading embedding model {MODEL_NAME} on {device}")
    model = SentenceTransformer(MODEL_NAME, device=device)
    if device.startswith("cuda"):
        model = model.half()
    return model


def embed(texts: list[str], device: str = "auto", batch_size: int = 64) -> list[list[float]]:
    if not texts:
        return []
    resolved = _resolve_device(device)
    model = _get_model(resolved)
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vectors.tolist()
