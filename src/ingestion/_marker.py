from functools import lru_cache

from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

from src.utils.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_models() -> dict:
    logger.info("Loading Marker models (first call only — may download weights)")
    return create_model_dict()


def convert_file(path: str) -> str:
    """Convert a PDF or image file to plain text using GPU-accelerated Marker models."""
    converter = PdfConverter(artifact_dict=_get_models())
    rendered = converter(path)
    text, _, _ = text_from_rendered(rendered)
    return text.strip()
