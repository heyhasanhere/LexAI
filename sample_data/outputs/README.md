# Sample Outputs

Draft outputs are generated at runtime by the system after ingesting documents from `../inputs/`.

To generate outputs against the sample inputs:

```bash
# 1. Start backing services
docker-compose up -d

# 2. Start the API server
uvicorn src.api.routes:app --reload --port 8000

# 3. Ingest the CUAD contracts (clean PDFs, good for first run)
python scripts/ingest_batch.py --input-dir sample_data/inputs/cuad/

# 4. Ingest the RVL-CDIP scanned images
python scripts/ingest_batch.py --input-dir sample_data/inputs/rvl_cdip/

# 5. Request a draft against the ingested contracts
curl -X POST http://localhost:8000/drafts \
  -H "Content-Type: application/json" \
  -d '{"document_ids": ["<id-from-step-3>"], "draft_type": "case_fact_summary"}'
```

Generated drafts will be saved here by the ingest script for reference.
