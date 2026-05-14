# Sample Input Documents

Two public datasets are used as sample inputs. No documents were fabricated.

---

## rvl_cdip/ — Scanned Document Images (OCR stress test)

**Source:** [RVL-CDIP](https://huggingface.co/datasets/RIPS-Goog-23/RVL-CDIP) (Ryerson Vision Lab Complex Document Information Processing), originally from the IIT-CDIP tobacco litigation archive.

**What it is:** Real scanned grayscale document images across 16 document categories. Documents are low-resolution, contain OCR artifacts, skew, faded ink, and noise — exactly the kind of messy input this system is designed to handle.

**What we downloaded:** 50 images (10 per class), test split, filtered to legal-relevant classes:

| Class | Files | Characteristics |
|---|---|---|
| `form` | form_00.jpg – form_09.jpg | Structured form layouts, often partially handwritten |
| `handwritten` | handwritten_00.jpg – handwritten_09.jpg | Fully handwritten pages, mixed legibility |
| `letter` | letter_00.jpg – letter_09.jpg | Typed correspondence, some with letterhead |
| `memo` | memo_00.jpg – memo_09.jpg | Internal memos, often with stamps and annotations |
| `invoice` | invoice_00.jpg – invoice_09.jpg | Tabular invoices, numeric fields |

**How to download more:**
```python
from datasets import load_dataset
ds = load_dataset('RIPS-Goog-23/RVL-CDIP', split='test', streaming=True)
```

---

## cuad/ — Commercial Legal Contracts (structured field extraction)

**Source:** [CUAD v1](https://huggingface.co/datasets/theatticusproject/cuad) (Contract Understanding Atticus Dataset), NeurIPS 2021. Maintained by The Atticus Project.

**What it is:** 510 real commercial legal contracts from SEC EDGAR filings, with expert annotations covering 41 clause categories (parties, dates, termination clauses, liability caps, etc.). These are clean PDFs with text layers — no OCR needed — which makes them ideal for validating the field extraction and retrieval layers independently of OCR quality.

**What we downloaded:** 10 contracts (affiliate agreements and co-branding agreements):

| File | Type | Size |
|---|---|---|
| CreditcardscomInc_...Affiliate Agreement.pdf | Affiliate agreement | 130KB |
| CybergyHoldingsInc_...Affiliate Agreement.pdf | Affiliate agreement | 131KB |
| DigitalCinemaDestinationsCorp_...Affiliate Agreement.pdf | Affiliate agreement | 212KB |
| LinkPlusCorp_...Affiliate Agreement.pdf | Affiliate agreement | 86KB |
| SouthernStarEnergyInc_...Affiliate Agreement.pdf | Affiliate agreement | 86KB |
| SteelVaultCorp_...Affiliate Agreement.pdf | Affiliate agreement | 79KB |
| TubeMediaCorp_...Affiliate Agreement.pdf | Affiliate agreement | 269KB |
| UnionDentalHoldingsInc_...Affiliate Agreement.pdf | Affiliate agreement | 78KB |
| UsioInc_...Affiliate Agreement 2.pdf | Affiliate agreement | 104KB |
| 2ThemartComInc_...Co-Branding Agreement.pdf | Co-branding / agency | 107KB |

**How to download more:**
```python
from datasets import load_dataset
ds = load_dataset('theatticusproject/cuad', split='train', streaming=True)
```

**License:** Creative Commons Attribution 4.0 (CC BY 4.0). Original contracts are public SEC filings.

---

## How the Two Datasets Complement Each Other

| Layer being tested | Dataset |
|---|---|
| OCR preprocessing (deskew, denoise, binarize) | RVL-CDIP images |
| Tesseract accuracy on real messy scans | RVL-CDIP images |
| Structured field extraction from clean text | CUAD contracts |
| Retrieval and grounding against real legal text | CUAD contracts |
| Draft generation from real legal content | CUAD contracts |
| Edit learning (simulate operator corrections) | CUAD contracts |

The RVL-CDIP images stress-test the ingestion layer. The CUAD contracts stress-test everything downstream of OCR.
