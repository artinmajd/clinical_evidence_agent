#!/usr/bin/env python3
"""MCP server exposing this project's retrieval and grounded-generation
pipeline as tools any MCP client (Claude Desktop, or another agent) can
call directly - without going through the FastAPI HTTP layer, and without
reimplementing any logic. Both tools below call the exact same
retrieve()/generate_answer() functions used by the CLI script, the API,
the eval harness, and the LangGraph agent.

Run with:
    python -m mcp_server.server

Uses the stdio transport, meant for a local client (like Claude Desktop)
to launch this as a subprocess and talk to it over stdin/stdout - not for
serving remote clients over a network.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field

# Load .env explicitly by path (not by searching upward from the current
# working directory) - Claude Desktop launches this server without
# reliably setting the working directory to the project root, so a
# bare load_dotenv() can silently find nothing.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

from api.generate import generate_answer
from retrieval.hybrid_search import connect_db, load_models, retrieve

DEFAULT_TOP_K = 10


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Load the embedding/rerank models and open the DB connection once,
    when the server starts - not on every tool call. Same idea as the
    `lifespan` function in api/main.py, just expressed in FastMCP's form
    of it. These are ordinary blocking calls (sentence-transformers,
    psycopg2); the tools below are defined as plain sync functions rather
    than async ones for the same reason - this server handles one local
    client and a handful of sequential tool calls, not concurrent network
    traffic, so there's no real benefit to threading blocking calls
    through asyncio here."""
    embed_model, rerank_model = load_models()
    conn = connect_db()
    try:
        yield {"embed_model": embed_model, "rerank_model": rerank_model, "conn": conn}
    finally:
        conn.close()


mcp = FastMCP("clinical_evidence_mcp", lifespan=app_lifespan)


class RetrieveHybridInput(BaseModel):
    """Input for a raw hybrid-search retrieval call, with no generation step."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(
        ...,
        description=(
            "A natural-language question about clinical trials, e.g. "
            "'What trials studied semaglutide for weight loss?'"
        ),
        min_length=3,
        max_length=500,
    )
    top_k: Optional[int] = Field(
        default=DEFAULT_TOP_K,
        description="Maximum number of trial excerpts to return, after reranking.",
        ge=1,
        le=20,
    )


class AskClinicalQuestionInput(BaseModel):
    """Input for the full grounded question-answering pipeline."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(
        ...,
        description=(
            "A natural-language question about clinical trials, e.g. "
            "'What were the primary endpoints of trials studying semaglutide?'"
        ),
        min_length=3,
        max_length=500,
    )


@mcp.tool(
    name="retrieve_hybrid",
    annotations={
        "title": "Hybrid Search Over Clinical Trials",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def retrieve_hybrid(params: RetrieveHybridInput, ctx: Context) -> str:
    """Retrieve the most relevant clinical trial excerpts for a question,
    without generating an answer.

    Runs this project's hybrid retrieval pipeline: dense (embedding)
    search and keyword (full-text) search over a corpus of obesity/GLP-1
    clinical trials, fused with reciprocal rank fusion, then reranked with
    a cross-encoder. Use this to inspect the underlying evidence itself,
    for example to check what the corpus actually contains before
    trusting a generated summary of it.

    Args:
        params (RetrieveHybridInput): Validated input containing:
            - question (str): The natural-language question to search for
            - top_k (Optional[int]): Max number of excerpts to return (1-20, default 10)

    Returns:
        str: JSON-formatted string with the following schema:
        {
            "count": int,              # Number of excerpts returned
            "results": [
                {
                    "nct_id": str,          # ClinicalTrials.gov identifier, e.g. "NCT04889183"
                    "chunk_text": str,      # The retrieved excerpt text
                    "rerank_score": float   # Cross-encoder relevance score (higher = more relevant)
                }
            ]
        }

    Examples:
        - Use when: "What does the corpus say about semaglutide dosing?" -> inspect raw evidence
        - Don't use when: you want a synthesized, cited answer (use ask_clinical_question instead)
    """
    resources = ctx.request_context.lifespan_context
    cur = resources["conn"].cursor()
    try:
        chunks = retrieve(
            cur,
            resources["embed_model"],
            resources["rerank_model"],
            params.question,
            top_k=params.top_k,
        )
    finally:
        cur.close()

    results = [
        {"nct_id": nct_id, "chunk_text": chunk_text, "rerank_score": score}
        for _, nct_id, chunk_text, score in chunks
    ]
    return json.dumps({"count": len(results), "results": results}, indent=2)


@mcp.tool(
    name="ask_clinical_question",
    annotations={
        "title": "Ask a Grounded Clinical Trials Question",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def ask_clinical_question(params: AskClinicalQuestionInput, ctx: Context) -> str:
    """Answer a natural-language question about clinical trials, grounded
    only in retrieved trial excerpts, with per-claim citations.

    Runs the full pipeline: hybrid retrieval (see retrieve_hybrid) followed
    by an LLM call constrained to answer only from the retrieved excerpts,
    citing an NCT ID after every claim. If the corpus doesn't contain
    enough information to answer, the answer says so explicitly instead of
    guessing - it never falls back on the model's own outside knowledge.

    Args:
        params (AskClinicalQuestionInput): Validated input containing:
            - question (str): The natural-language question to answer

    Returns:
        str: JSON-formatted string with the following schema:
        {
            "answer": str,          # The generated answer, with inline [NCTxxxxxxxx] citations
            "citations": [str]      # Sorted list of unique NCT IDs actually cited in the answer
        }

    Examples:
        - Use when: "What were the primary endpoints of trials studying semaglutide?"
        - Don't use when: you want raw evidence without a synthesized answer (use retrieve_hybrid instead)
    """
    resources = ctx.request_context.lifespan_context
    cur = resources["conn"].cursor()
    try:
        chunks = retrieve(
            cur, resources["embed_model"], resources["rerank_model"], params.question
        )
    finally:
        cur.close()

    answer, citations = generate_answer(params.question, chunks)
    return json.dumps({"answer": answer, "citations": citations}, indent=2)


if __name__ == "__main__":
    mcp.run()
