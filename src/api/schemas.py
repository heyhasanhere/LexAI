from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str


class ExtractedFieldsSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document_type: str | None = None
    parties: list[dict[str, Any]] = []
    key_dates: list[dict[str, Any]] = []
    key_clauses: list[dict[str, Any]] = []
    flags_and_risks: list[dict[str, Any]] = []
    matter_timeline: list[dict[str, Any]] = []
    obligation_tracker: list[dict[str, Any]] = []
    risk_summary: dict[str, Any] | None = None
    clause_library: list[dict[str, Any]] = []
    party_profile: list[dict[str, Any]] = []
    due_diligence_checklist: list[dict[str, Any]] = []
    anomaly_report: list[dict[str, Any]] = []
    transcript_summary: list[dict[str, Any]] = []
    case_law_citations: list[dict[str, Any]] = []
    document_gap_report: list[dict[str, Any]] = []
    audit_trail: list[dict[str, Any]] = []
    source_grounding: list[dict[str, Any]] = []
    extraction_notes: str | None = None
    flags: list[str] = []


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


class LLMConfigResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    api_key_set: bool
    max_tokens: int


class LLMConfigUpdate(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    max_tokens: int | None = None
