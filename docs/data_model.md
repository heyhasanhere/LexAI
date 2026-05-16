# Data Model

Conceptual entity designs for the system. Exact schemas (SQL DDL, Pydantic models) are written during implementation.

---

## Document

Represents a single ingested file. Tracks processing status and stores the structured fields extracted from it.

| Field | Type | Notes |
|---|---|---|
| `document_id` | string | uuid4 |
| `filename` | string | original uploaded filename |
| `file_type` | string | `pdf` / `image` / `text` |
| `upload_timestamp` | datetime | |
| `status` | enum | `pending` → `processing` → `ready` / `failed` |
| `page_count` | int | |
| `fields` | ExtractedFields | null until extraction completes |
| `extraction_notes` | string | LLM commentary on ambiguous fields |
| `flags` | string[] | e.g. `page_2_missing`, `low_ocr_confidence` |

---

## ExtractedFields

Structured output of the field extraction step. All list fields default to empty; `document_type` and `risk_summary` default to `null`. The LLM omits sections it finds no evidence for and records ambiguities in `extraction_notes`. The applicable sections vary by document type.

| Field | Type | Notes |
|---|---|---|
| `document_type` | string \| null | e.g. `contract`, `deed`, `invoice`, `medical_record` |
| `parties` | Party[] | all named people and organisations with roles |
| `key_dates` | KeyDate[] | all dates that matter (signing, deadlines, expirations) |
| `key_clauses` | KeyClause[] | important terms, conditions, and provisions |
| `flags_and_risks` | FlagRisk[] | both quality issues and substantive risks |
| `matter_timeline` | TimelineEvent[] | chronological events and milestones |
| `obligation_tracker` | Obligation[] | obligations per party with due dates or conditions |
| `risk_summary` | RiskSummary \| null | overall risk level with itemised breakdown |
| `clause_library` | ClauseEntry[] | verbatim or near-verbatim extracted clauses |
| `party_profile` | PartyProfile[] | entity summaries with identifiers |
| `due_diligence_checklist` | ChecklistItem[] | expected elements with found/missing status |
| `anomaly_report` | Anomaly[] | deviations from standard structure or wording |
| `transcript_summary` | TranscriptEntry[] | speaker statements from depositions or hearings |
| `case_law_citations` | CaseLaw[] | referenced cases or statutes with context |
| `document_gap_report` | GapEntry[] | expected elements with Present/Missing/Illegible status |
| `audit_trail` | AuditEntry[] | actor, action, and timestamp records |
| `source_grounding` | GroundingEntry[] | important facts not captured in other sections |
| `extraction_notes` | string \| null | LLM commentary on the document and extraction quality |
| `flags` | string[] | structural/quality issues only (missing pages, OCR problems, truncated content) |

**Sub-entity schemas:**

| Sub-entity | Fields |
|---|---|
| Party | `role`, `name`, `identifier`, `page` |
| KeyDate | `label`, `date`, `page`, `alert` |
| KeyClause | `name`, `value`, `page` |
| FlagRisk | `description`, `page` |
| TimelineEvent | `date`, `event`, `page` |
| Obligation | `party`, `obligation`, `due`, `page` |
| RiskSummary | `overall`, `level` (High\|Medium\|Low), `items: [{ severity, description, page }]` |
| ClauseEntry | `clause_type`, `text`, `page` |
| PartyProfile | `entity`, `role`, `identifiers`, `page` |
| ChecklistItem | `item`, `found` (bool), `page` |
| Anomaly | `clause`, `deviation`, `page` |
| TranscriptEntry | `speaker`, `statement`, `page` |
| CaseLaw | `case`, `context`, `page` |
| GapEntry | `expected`, `status` (Present\|Missing\|Illegible) |
| AuditEntry | `actor`, `action`, `timestamp`, `page` |
| GroundingEntry | `field`, `value`, `page` |

---

## Chunk

A contiguous span of text from a document, stored in the vector store with its metadata.

| Field | Type | Notes |
|---|---|---|
| `chunk_id` | string | `{document_id}-chunk-{index}` |
| `document_id` | string | |
| `page_number` | int | |
| `chunk_index` | int | sequential within the document |
| `char_start` | int | character offset in full document text |
| `char_end` | int | |
| `text` | string | |
| `ocr_confidence` | float | 0.0–1.0, average of per-word Tesseract confidence |
| `token_count` | int | |

Chunks live in ChromaDB, not Postgres. The metadata fields above are stored alongside the embedding for filtering at retrieval time.

---

## Draft

A generated Case Fact Summary, capturing both the system-generated version and the operator's final submission.

| Field | Type | Notes |
|---|---|---|
| `draft_id` | string | |
| `document_ids` | string[] | which documents this draft covers |
| `draft_type` | string | `case_fact_summary` |
| `created_at` | datetime | |
| `status` | enum | `generated` → `in_review` → `submitted` |
| `original_text` | string | system-generated, immutable after creation |
| `submitted_text` | string | operator's final version |
| `ungrounded_sentences` | string[] | sentences flagged by the grounding verifier |
| `edit_patterns_used` | string[] | pattern IDs injected at generation time |

---

## Citation

Maps a span in the draft text back to the specific source chunk that supports it. Citations are embedded in the `citations_json` column of the `drafts` table — they are not stored as a separate table.

| Field | Type | Notes |
|---|---|---|
| `document_id` | string | |
| `chunk_id` | string | `{document_id}-chunk-{index}` |
| `draft_char_start` | int | character offset of the citation marker in the draft text |
| `draft_char_end` | int | |

---

## EditPattern

A reusable correction pattern extracted from an operator's edit. Stored in Postgres and retrieved at generation time to guide future drafts.

| Field | Type | Notes |
|---|---|---|
| `pattern_id` | string | |
| `document_type` | string | null = applies to all document types |
| `section` | string | which draft section (e.g. `parties`, `key_dates`) |
| `edit_type` | enum | `correction`, `addition`, `deletion`, `reformat` |
| `trigger` | string | one sentence: when to apply this pattern |
| `original_text` | string | representative before-text |
| `corrected_text` | string | representative after-text |
| `frequency` | int | how many times observed across drafts |
| `first_seen` | datetime | |
| `last_seen` | datetime | |
