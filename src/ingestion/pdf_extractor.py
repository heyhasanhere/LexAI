from dataclasses import dataclass, field
from pathlib import Path

from pdfminer.high_level import extract_text_to_fp
from pdfminer.layout import LAParams
from pdf2image import convert_from_path
from PIL import Image
import io

from src.ingestion.ocr import OCRResult, run_ocr
from src.utils.logger import get_logger

logger = get_logger(__name__)

IMAGE_ONLY_THRESHOLD = 100  # characters per page below which we treat the page as image-only


@dataclass
class PageResult:
    page_number: int           # 1-indexed
    text: str
    ocr_confidence: float      # 1.0 for native text-layer pages
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


def _extract_text_layer(pdf_path: Path) -> list[str]:
    """Extract per-page text via pdfminer. Returns one string per page."""
    pages = []
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextContainer
        for page_layout in extract_pages(str(pdf_path)):
            page_text = "".join(
                element.get_text()
                for element in page_layout
                if isinstance(element, LTTextContainer)
            )
            pages.append(page_text)
    except Exception as e:
        logger.error(f"pdfminer extraction failed: {e}")
    return pages


def extract_pdf(
    pdf_path: Path,
    dpi: int = 300,
    image_only_threshold: int = IMAGE_ONLY_THRESHOLD,
    ocr_kwargs: dict | None = None,
) -> PDFResult:
    ocr_kwargs = ocr_kwargs or {}
    result = PDFResult()

    text_pages = _extract_text_layer(pdf_path)

    # Render all pages to images upfront only if any page needs OCR
    needs_ocr = [
        i for i, t in enumerate(text_pages)
        if len(t.strip()) < image_only_threshold
    ]

    images: list[Image.Image] = []
    if needs_ocr or not text_pages:
        try:
            images = convert_from_path(str(pdf_path), dpi=dpi)
        except Exception as e:
            logger.error(f"pdf2image conversion failed: {e}")

    total_pages = max(len(text_pages), len(images))

    for i in range(total_pages):
        page_num = i + 1
        text = text_pages[i] if i < len(text_pages) else ""

        if len(text.strip()) >= image_only_threshold:
            result.pages.append(PageResult(
                page_number=page_num,
                text=text,
                ocr_confidence=1.0,
                ocr_used=False,
            ))
            continue

        if i >= len(images):
            logger.warning(f"Page {page_num}: no image available for OCR")
            result.pages.append(PageResult(
                page_number=page_num,
                text="",
                ocr_confidence=0.0,
                ocr_used=True,
                failed=True,
            ))
            continue

        ocr_result: OCRResult = run_ocr(images[i], **ocr_kwargs)
        result.pages.append(PageResult(
            page_number=page_num,
            text=ocr_result.text,
            ocr_confidence=ocr_result.confidence,
            ocr_used=True,
            failed=ocr_result.failed,
        ))
        if ocr_result.failed:
            logger.warning(f"Page {page_num}: OCR failed")
        else:
            logger.info(f"Page {page_num}: OCR confidence={ocr_result.confidence:.2f}")

    return result
