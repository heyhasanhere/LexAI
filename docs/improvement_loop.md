# Operator Edit Learning — Design

## Problem

A first-pass draft generated from OCR'd legal documents will be imperfect. Operators will correct it. If those corrections are discarded after submission, the same mistakes will appear in every similar document in the future.

The improvement loop makes operator corrections reusable. The goal is not to fine-tune a model — it is to accumulate a structured library of "what a good draft looks like for this document type and this section" and inject that knowledge into future generation prompts as few-shot examples.

---

## What Gets Captured

When an operator submits an edited draft, the system diffs the original system-generated text against the submitted text. Each changed region is treated as an edit candidate, tagged with:

- which draft section the change falls in (e.g. `Parties`, `Key Dates`)
- the original text span
- the corrected text span

---

## Classification

Each edit candidate is sent to the LLM to determine:

1. **Edit type** — `correction`, `addition`, `deletion`, or `reformat`
2. **Trigger** — one sentence describing when this pattern should be applied in the future
3. **Generalizable** — is this a structural/formatting preference that applies to similar documents, or is it specific to this document's content?

Only generalizable edits are stored as patterns. Document-specific factual corrections (e.g., a wrong name) are logged but not stored.

---

## Pattern Storage and Retrieval

Patterns are stored in Postgres, keyed by `(document_type, section, edit_type)`.

Near-duplicate patterns (same trigger, slightly different wording) are merged rather than stored separately. Each stored pattern accumulates a frequency count as more operators make the same correction.

At draft generation time, the top patterns by frequency for the relevant document type and sections are retrieved and injected into the generation prompt as a "learned preferences" block. Patterns below a minimum frequency threshold are stored but not yet injected — a single idiosyncratic edit should not distort future drafts.

---

## Effect on Generation

Injected patterns appear in the prompt as few-shot examples: here is what a previous draft contained, here is how an operator corrected it, apply this preference when generating. The LLM applies the pattern without any model weight changes.
