import mimetypes
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # pymupdf

from src.ingestion._marker import convert_file
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
    ".pdf":  "application/pdf",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif":  "image/tiff",
    ".bmp":  "image/bmp",
    ".txt":  "text/plain",
    ".html": "text/html",
    ".htm":  "text/html",
}


@dataclass
class LoadedDocument:
    path: Path
    file_type: str
    pages: list[PageResult] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def page_annotated_text(self) -> str:
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
    image_only_threshold: int = 100,
    **_ignored,
) -> LoadedDocument:
    mime, _ = mimetypes.guess_type(str(path))
    if mime not in SUPPORTED_MIME_TYPES:
        mime = _EXT_MIME.get(Path(path).suffix.lower())
    if not mime or mime not in SUPPORTED_MIME_TYPES:
        raise ValueError(f"Unsupported file type: {Path(path).suffix!r} ({path.name})")

    if mime == "application/pdf":
        pdf_result: PDFResult = extract_pdf(path, image_only_threshold=image_only_threshold)
        return LoadedDocument(path=path, file_type="pdf", pages=pdf_result.pages)

    if mime and mime.startswith("image/"):
        return _load_image(path)

    if mime == "text/plain":
        text = path.read_text(encoding="utf-8", errors="replace")
        return LoadedDocument(
            path=path,
            file_type="text",
            pages=[PageResult(page_number=1, text=text, ocr_confidence=1.0, ocr_used=False)],
        )

    if mime == "text/html":
        raw = path.read_text(encoding="utf-8", errors="replace")
        return LoadedDocument(
            path=path,
            file_type="text",
            pages=[PageResult(page_number=1, text=_strip_html(raw), ocr_confidence=1.0, ocr_used=False)],
        )

    raise ValueError(f"Unhandled MIME type: {mime}")


def _load_image(path: Path) -> LoadedDocument:
    doc = fitz.open(str(path))
    pages = []

    for idx in range(len(doc)):
        pix = doc[idx].get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            pix.save(tmp.name)
            tmp_path = tmp.name

        try:
            text = convert_file(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        pages.append(PageResult(
            page_number=idx + 1,
            text=text,
            ocr_confidence=1.0,
            ocr_used=True,
            failed=not bool(text.strip()),
        ))

    doc.close()
    return LoadedDocument(path=path, file_type="image", pages=pages)


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
