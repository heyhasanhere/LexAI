import numpy as np
import cv2
from PIL import Image
from deskew import determine_skew
import pytesseract
from dataclasses import dataclass

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OCRResult:
    text: str
    confidence: float  # 0.0–1.0 average word confidence
    failed: bool = False


def _pil_to_cv2(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def _cv2_to_pil(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def _deskew(image: Image.Image) -> Image.Image:
    grayscale = np.array(image.convert("L"))
    angle = determine_skew(grayscale)
    if angle is None or abs(angle) < 0.5:
        return image
    arr = _pil_to_cv2(image)
    (h, w) = arr.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(arr, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return _cv2_to_pil(rotated)


def _enhance_contrast(image: Image.Image) -> Image.Image:
    gray = cv2.cvtColor(_pil_to_cv2(image), cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return Image.fromarray(enhanced)


def _denoise(image: Image.Image) -> Image.Image:
    gray = np.array(image.convert("L"))
    denoised = cv2.fastNlMeansDenoising(gray, h=10)
    return Image.fromarray(denoised)


def _binarize(image: Image.Image) -> Image.Image:
    gray = np.array(image.convert("L"))
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(binary)


def run_ocr(
    image: Image.Image,
    deskew: bool = True,
    denoise: bool = True,
    contrast_enhance: bool = True,
    binarize: bool = True,
    lang: str = "eng",
    oem: int = 3,
    psm: int = 6,
) -> OCRResult:
    try:
        if deskew:
            image = _deskew(image)
        if contrast_enhance:
            image = _enhance_contrast(image)
        if denoise:
            image = _denoise(image)
        if binarize:
            image = _binarize(image)

        config = f"--oem {oem} --psm {psm}"
        data = pytesseract.image_to_data(image, lang=lang, config=config, output_type=pytesseract.Output.DICT)

        words = [
            (data["text"][i], int(data["conf"][i]))
            for i in range(len(data["text"]))
            if data["text"][i].strip() and int(data["conf"][i]) >= 0
        ]

        if not words:
            logger.warning("Tesseract returned no words")
            return OCRResult(text="", confidence=0.0, failed=True)

        text = pytesseract.image_to_string(image, lang=lang, config=config)
        avg_confidence = sum(c for _, c in words) / len(words) / 100.0
        return OCRResult(text=text, confidence=avg_confidence)

    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return OCRResult(text="", confidence=0.0, failed=True)
