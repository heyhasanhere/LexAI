from dataclasses import dataclass

import nltk
import tiktoken

from src.utils.logger import get_logger

logger = get_logger(__name__)

try:
    nltk.data.find("tokenizers/punkt_tab")
except LookupError:
    nltk.download("punkt_tab", quiet=True)

_tokenizer = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_tokenizer.encode(text))


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    tokens = _tokenizer.encode(text)
    return _tokenizer.decode(tokens[:max_tokens])


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    page_number: int
    chunk_index: int
    char_start: int
    char_end: int
    text: str
    ocr_confidence: float
    token_count: int


def chunk_document(
    document_id: str,
    pages: list[tuple[int, str, float]],  # (page_number, text, ocr_confidence)
    chunk_size: int = 512,
    overlap: int = 64,
    min_chunk_size: int = 50,
) -> list[Chunk]:
    full_text = ""
    page_map: list[tuple[int, int, int, float]] = []  # (char_start, char_end, page_number, confidence)

    for page_number, text, confidence in pages:
        start = len(full_text)
        full_text += text + "\n\n"
        end = len(full_text)
        page_map.append((start, end, page_number, confidence))

    sentences = nltk.sent_tokenize(full_text)

    chunks: list[Chunk] = []
    current_sentences: list[str] = []
    current_tokens = 0
    char_cursor = 0
    chunk_index = 0
    overlap_text = ""

    for sentence in sentences:
        sentence_tokens = _count_tokens(sentence)

        if current_tokens + sentence_tokens > chunk_size and current_sentences:
            chunk_text = overlap_text + " ".join(current_sentences)
            token_count = _count_tokens(chunk_text)

            if token_count >= min_chunk_size:
                char_start = full_text.find(current_sentences[0], char_cursor)
                char_end = char_start + len(chunk_text)
                page_number, confidence = _get_page_info(char_start, page_map)

                chunks.append(Chunk(
                    chunk_id=f"{document_id}-chunk-{chunk_index:03d}",
                    document_id=document_id,
                    page_number=page_number,
                    chunk_index=chunk_index,
                    char_start=char_start,
                    char_end=char_end,
                    text=chunk_text.strip(),
                    ocr_confidence=confidence,
                    token_count=token_count,
                ))
                chunk_index += 1
                char_cursor = char_start

            overlap_tokens = _tokenizer.encode(" ".join(current_sentences))[-overlap:]
            overlap_text = _tokenizer.decode(overlap_tokens) + " "
            current_sentences = []
            current_tokens = _count_tokens(overlap_text)

        current_sentences.append(sentence)
        current_tokens += sentence_tokens

    if current_sentences:
        chunk_text = overlap_text + " ".join(current_sentences)
        if _count_tokens(chunk_text) >= min_chunk_size:
            char_start = full_text.find(current_sentences[0], char_cursor)
            char_end = char_start + len(chunk_text)
            page_number, confidence = _get_page_info(char_start, page_map)

            chunks.append(Chunk(
                chunk_id=f"{document_id}-chunk-{chunk_index:03d}",
                document_id=document_id,
                page_number=page_number,
                chunk_index=chunk_index,
                char_start=char_start,
                char_end=char_end,
                text=chunk_text.strip(),
                ocr_confidence=confidence,
                token_count=_count_tokens(chunk_text),
            ))

    logger.info(f"document={document_id} chunks={len(chunks)}")
    return chunks


def _get_page_info(char_pos: int, page_map: list[tuple[int, int, int, float]]) -> tuple[int, float]:
    for start, end, page_number, confidence in page_map:
        if start <= char_pos < end:
            return page_number, confidence
    return page_map[-1][2], page_map[-1][3]
