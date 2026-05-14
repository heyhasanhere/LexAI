from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str


class PartySchema(BaseModel):
    role: str
    name: str | None
    entity_type: str | None
    confidence: str


class ExtractedFieldsSchema(BaseModel):
    document_type: str | None
    parties: list[PartySchema]
    property_address: str | None
    legal_description: str | None
    recording_date: str | None
    instrument_number: str | None
    loan_amount: float | None
    maturity_date: str | None
    notary_present: bool | None
    key_value_pairs: list[dict[str, Any]]
    extraction_notes: str | None
    flags: list[str]


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    file_type: str
    upload_timestamp: datetime
    status: str
    page_count: int | None
    fields: ExtractedFieldsSchema | None
    flags: list[str]


class DocumentListResponse(BaseModel):
    total: int
    documents: list[DocumentResponse]


class CitationSchema(BaseModel):
    document_id: str
    chunk_id: str
    draft_char_start: int
    draft_char_end: int


class DraftRequest(BaseModel):
    document_ids: list[str]
    draft_type: str = "case_fact_summary"


class DraftResponse(BaseModel):
    draft_id: str
    document_ids: list[str]
    draft_type: str
    created_at: datetime
    status: str
    draft_text: str
    ungrounded_sentences: list[str]
    citations: list[CitationSchema]
    patterns_used: list[str]


class DraftListResponse(BaseModel):
    total: int
    drafts: list[DraftResponse]


class SubmitDraftRequest(BaseModel):
    submitted_text: str


class SubmitDraftResponse(BaseModel):
    draft_id: str
    status: str
    patterns_extracted: int
    pattern_ids: list[str]


class PatternResponse(BaseModel):
    pattern_id: str
    document_type: str | None
    section: str
    edit_type: str
    trigger: str
    original_text: str
    corrected_text: str
    frequency: int
    first_seen: datetime
    last_seen: datetime


class PatternListResponse(BaseModel):
    total: int
    patterns: list[PatternResponse]


class HealthResponse(BaseModel):
    status: str
    vector_store: str
    database: str
    ocr_available: bool


class ErrorResponse(BaseModel):
    error: str
    message: str
    detail: str | None = None
