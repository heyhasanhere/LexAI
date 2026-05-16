import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from src.ingestion.ocr import run_ocr
from src.ingestion.pdf_extractor import PDFResult, PageResult, extract_pdf
from src.utils.logger import get_logger

logger = get_logger(__name__)

SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/tiff",
    "image/bmp",
    "text/plain",
    "text/html",
}

_EXT_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
}


@dataclass
class LoadedDocument:
    path: Path
    file_type: str          # "pdf" | "image" | "text"
    pages: list[PageResult] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def page_annotated_text(self) -> str:
        """Full text with [PAGE N] markers so the LLM can produce accurate page refs."""
        parts = []
        for p in self.pages:
            if p.text.strip():
                parts.append(f"[PAGE {p.page_number}]\n{p.text.strip()}")
        return "\n\n".join(parts)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def flags(self) -> list[str]:
        flags = []
        for p in self.pages:
            if p.failed:
                flags.append(f"page_{p.page_number}_ocr_failed")
            elif p.ocr_used and p.ocr_confidence < 0.40:
                flags.append(f"page_{p.page_number}_low_confidence")
        return flags


def load_document(
    path: Path,
    ocr_kwargs: dict | None = None,
    dpi: int = 300,
    image_only_threshold: int = 100,
) -> LoadedDocument:
    ocr_kwargs = ocr_kwargs or {}
    mime, _ = mimetypes.guess_type(str(path))

    # Fall back to extension-based detection when mimetypes returns nothing useful
    if mime not in SUPPORTED_MIME_TYPES:
        mime = _EXT_MIME.get(Path(path).suffix.lower())

    if not mime or mime not in SUPPORTED_MIME_TYPES:
        raise ValueError(f"Unsupported file type: {Path(path).suffix!r} ({path.name})")

    if mime == "application/pdf":
        pdf_result: PDFResult = extract_pdf(path, dpi=dpi, image_only_threshold=image_only_threshold, ocr_kwargs=ocr_kwargs)
        return LoadedDocument(path=path, file_type="pdf", pages=pdf_result.pages)

    if mime and mime.startswith("image/"):
        return _load_image(path, ocr_kwargs)

    if mime == "text/plain":
        text = path.read_text(encoding="utf-8", errors="replace")
        return LoadedDocument(
            path=path,
            file_type="text",
            pages=[PageResult(page_number=1, text=text, ocr_confidence=1.0, ocr_used=False)],
        )

    if mime == "text/html":
        raw = path.read_text(encoding="utf-8", errors="replace")
        text = _strip_html(raw)
        return LoadedDocument(
            path=path,
            file_type="text",
            pages=[PageResult(page_number=1, text=text, ocr_confidence=1.0, ocr_used=False)],
        )

    raise ValueError(f"Unhandled MIME type: {mime}")


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _load_image(path: Path, ocr_kwargs: dict) -> LoadedDocument:
    image = Image.open(path)
    pages = []

    # Handle multi-page TIFFs
    frame_count = getattr(image, "n_frames", 1)
    for i in range(frame_count):
        if frame_count > 1:
            image.seek(i)
            frame = image.copy()
        else:
            frame = image

        ocr_result = run_ocr(frame, **ocr_kwargs)
        pages.append(PageResult(
            page_number=i + 1,
            text=ocr_result.text,
            ocr_confidence=ocr_result.confidence,
            ocr_used=True,
            failed=ocr_result.failed,
        ))

    return LoadedDocument(path=path, file_type="image", pages=pages)
