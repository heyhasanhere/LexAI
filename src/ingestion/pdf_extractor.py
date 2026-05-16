import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # pymupdf

from src.ingestion._marker import convert_file
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PageResult:
    page_number: int
    text: str
    ocr_confidence: float
    ocr_used: bool
    failed: bool = False


@dataclass
class PDFResult:
    pages: list[PageResult] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def page_count(self) -> int:
        return len(self.pages)


def extract_pdf(
    pdf_path: Path,
    image_only_threshold: int = 100,
    **_ignored,
) -> PDFResult:
    result = PDFResult()
    doc = fitz.open(str(pdf_path))

    for idx in range(len(doc)):
        page_num = idx + 1
        page = doc[idx]
        text = page.get_text().strip()

        if len(text) >= image_only_threshold:
            result.pages.append(PageResult(
                page_number=page_num,
                text=text,
                ocr_confidence=1.0,
                ocr_used=False,
            ))
            logger.info(f"Page {page_num}: text layer ({len(text)} chars)")
        else:
            # Render page at 2x scale (~144 DPI) and run Marker OCR
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                pix.save(tmp.name)
                tmp_path = tmp.name

            try:
                ocr_text = convert_file(tmp_path)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

            result.pages.append(PageResult(
                page_number=page_num,
                text=ocr_text,
                ocr_confidence=1.0,
                ocr_used=True,
                failed=not bool(ocr_text.strip()),
            ))
            logger.info(f"Page {page_num}: Marker OCR ({len(ocr_text)} chars)")

    doc.close()
    return result
