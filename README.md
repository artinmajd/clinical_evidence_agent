# Clinical Evidence Research Agent

An agent that answers clinical-research questions (e.g. "what were the primary
endpoints across phase 3 GLP-1 trials since 2023") by retrieving from a corpus
of public trial records and abstracts, extracting structured claims, and
returning an answer where every sentence traces back to a cited source.

Built as a learning project to go deep, step by step, on the parts of AI
engineering that don't show up in a weekend RAG demo: evaluation, tracing,
guardrails, agent orchestration, and deployment. No GPU required to build or
run it end to end; a self-hosted GPU backend is a config swap, not a rewrite.

## Status
Just started. See PROGRESS.md for where things stand and NOTES.md for
concept explanations as we go.

## Data sources
- ClinicalTrials.gov API v2 (public, no auth needed for normal use)
- PubMed abstracts via NCBI E-utilities (get a free API key before bulk pulls)

## Running locally
Setup instructions will land here as the project takes shape.
