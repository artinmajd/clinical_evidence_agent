# Clinical Evidence Research Agent

An agentic RAG system that answers clinical-research questions (e.g. "what were the primary endpoints across phase 3 GLP-1 trials since 2023") against a real corpus of ClinicalTrials.gov trial records, with every claim tracing back to a cited NCT ID.

Built as a learning project to go deep, step by step, on the parts of AI engineering that don't show up in a weekend RAG demo: agent orchestration, evaluation and tracing, guardrails, access control, and a full deploy to Kubernetes. No GPU required; the whole pipeline runs on CPU end to end.

## What it does

- Retrieves relevant trials with hybrid search (dense embeddings + keyword search fused with RRF, then cross-encoder reranking) against 415 real phase 3 trials pulled from the ClinicalTrials.gov API.
- Runs the retrieval-through-answer flow as a **LangGraph** agent (plan, retrieve, extract, self-check, respond), with Postgres-backed checkpointing so state survives across steps.
- Pauses for **human review** via a LangGraph `interrupt()` whenever an answer comes back ungrounded or fails a guardrail, instead of returning it anyway.
- Applies two independent guardrails before an answer reaches the user: a prompt-injection scan on every retrieved chunk, and a deterministic citation check that flags uncited or fabricated NCT IDs.
- Enforces row-level **access control**: trials are tagged public/restricted, and a caller's role (researcher vs. clinician) determines what the SQL query is even allowed to fetch, not just what gets filtered afterward.
- Is evaluated continuously: a 66-question golden set is scored by an LLM-as-judge for faithfulness and completeness, traced through **Langfuse**, and gated in **CI** (GitHub Actions fails the build if quality regresses).
- Is exposed three ways: a FastAPI HTTP API, an **MCP** server (so it can be called directly as tools from Claude Desktop), and a small **React + TypeScript** web UI.
- Deploys to **Google Kubernetes Engine (GKE Autopilot)** via Terraform, with HPA autoscaling and a one-command `deploy.sh` for a full teardown-and-rebuild cycle.

## Architecture

```
ClinicalTrials.gov API
        |
   ingestion / processing  (chunk, embed with PubMedBERT)
        |
   Postgres + pgvector  (hybrid_search: dense + keyword, RRF, rerank)
        |
   guardrails  (prompt-injection scan, access control by role)
        |
   LangGraph agent  (plan -> retrieve -> extract -> self-check -> respond)
        |                      \
   citation guardrail       human-review interrupt (on low confidence)
        |
   grounded, cited answer
        |
   FastAPI /ask   |   MCP tools (Claude Desktop)   |   React frontend
```

Deployed on GKE Autopilot behind a LoadBalancer, with the eval harness running as a GitHub Actions gate on every push to `main`.

## Tech stack

**Retrieval & data:** PostgreSQL, pgvector, PubMedBERT embeddings (sentence-transformers), cross-encoder reranking, ClinicalTrials.gov API v2

**Agent & LLM:** LangGraph, LangGraph Postgres checkpointing, OpenAI (gpt-4o-mini for generation, gpt-4o for LLM-as-judge), MCP (Model Context Protocol)

**Guardrails & eval:** LLM Guard (ONNX prompt-injection classifier), a deterministic citation/faithfulness checker, Langfuse tracing, a 66-question golden-set eval harness wired into GitHub Actions

**Serving & infra:** FastAPI, React + TypeScript (Vite, served via nginx), Docker, Terraform (GKE Autopilot + Artifact Registry), Kubernetes (Deployment, Service, HPA), k6 load testing

## Status

All planned phases are complete:

1. Thin slice: ingest, hybrid retrieval, grounded generation with citations
2. Eval harness (Langfuse tracing, LLM-as-judge, CI quality gate)
3. LangGraph agent with checkpointing, human-review interrupts, and an MCP tool server
4. Guardrails (prompt-injection scan, citation check) and role-based access control
5. Infrastructure as code: Docker, Terraform, Kubernetes, HPA, load testing, and a React frontend

See `PROGRESS.md` for the detailed phase-by-phase log and `CHALLENGES.md` / `NOTES.md` for real bugs hit and concepts explained along the way. The GKE cluster is torn down between demos (`terraform destroy`) to avoid ongoing cost; `deploy.sh` brings it back up with one command.

## Data sources

- ClinicalTrials.gov API v2 (public, no auth needed for normal use)
- PubMed abstracts via NCBI E-utilities (get a free API key before bulk pulls)

## Running locally

1. Copy `.env` with the following variables set: `SUPABASE_DB_HOST`, `SUPABASE_DB_PORT`, `SUPABASE_DB_NAME`, `SUPABASE_DB_USER`, `SUPABASE_DB_PASSWORD`, `OPENAI_API_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL`.
2. `pip install -r requirements.txt`
3. Run the API: `uvicorn api.main:app --reload` (serves `POST /ask`), or query the pipeline directly with `python -m retrieval.hybrid_search`.
4. Run the eval harness: `python -m eval.run_eval --limit 5` (drop `--limit` for the full 66-question set).
5. Run the MCP server for use from Claude Desktop: `python mcp_server/server.py`.

## Deploying

```
./deploy.sh
```

Runs `terraform apply` to (re)create the GKE Autopilot cluster and Artifact Registry, builds and pushes both the backend and frontend Docker images, applies the Kubernetes manifests (Deployment, Service, HPA) for both, and waits for a live, answering LoadBalancer IP. See `deploy.sh` and `terraform/main.tf` for details, and `k8s/` for the manifests.

## Repository layout

- `ingestion/`, `processing/`: pull and chunk/embed the ClinicalTrials.gov corpus
- `retrieval/`: hybrid search (dense + keyword + rerank), access control enforcement
- `guardrails/`: prompt-injection scanning, citation/faithfulness checking, role-based access control
- `agent/`: the LangGraph state graph
- `mcp_server/`: MCP tool server for Claude Desktop
- `api/`: FastAPI app
- `frontend/`: React + TypeScript UI
- `eval/`: golden-set eval harness (LLM-as-judge, CI gate)
- `terraform/`, `k8s/`, `Dockerfile`, `deploy.sh`: infrastructure and deployment
- `loadtest/`: k6 load test
