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

Structured output of the field extraction step. All fields are nullable — the LLM returns `null` for anything it cannot extract with confidence, and explains why in `extraction_notes`.

| Field | Type | Notes |
|---|---|---|
| `document_type` | string | e.g. `deed_of_trust`, `lien_release`, `title_commitment` |
| `parties` | Party[] | list of all identified parties with roles |
| `property_address` | string | |
| `legal_description` | string | |
| `recording_date` | date | |
| `instrument_number` | string | |
| `loan_amount` | float | |
| `maturity_date` | date | |
| `notary_present` | bool | |
| `key_value_pairs` | list | catch-all for fields not covered above |
| `extraction_notes` | string | |

**Party sub-entity:**

| Field | Type | Notes |
|---|---|---|
| `role` | string | `grantor`, `grantee`, `trustee`, `beneficiary`, etc. |
| `name` | string | |
| `entity_type` | string | `individual`, `trust`, `corporation`, `llc` |
| `confidence` | enum | `high`, `medium`, `low` |

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

Maps a span in the draft text back to the specific source chunk that supports it.

| Field | Type | Notes |
|---|---|---|
| `citation_id` | string | |
| `draft_id` | string | |
| `document_id` | string | |
| `chunk_id` | string | |
| `draft_char_start` | int | location of citation in draft text |
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
