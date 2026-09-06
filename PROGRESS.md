# Progress log

Track what's actually done, phase by phase, so any future session (or you,
weeks later) can see where we left off without re-reading everything.

## Phase 1 — thin slice (ingest, hybrid retrieve, cited answer)
- [ ] Step 1: explore the ClinicalTrials.gov API, understand the data shape
- [ ] Step 2: pull a small corpus for one therapeutic area
- [ ] Step 3: chunk + embed, store in Postgres/pgvector
- [ ] Step 4: hybrid retrieval (dense + full-text) + rerank
- [ ] Step 5: one LLM call, cited answer, FastAPI endpoint
