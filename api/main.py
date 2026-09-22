from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from langfuse import get_client, observe
from pydantic import BaseModel

# Load .env before importing modules that read credentials at import time
# (e.g. api.generate constructs OpenAI() using OPENAI_API_KEY).
load_dotenv()

from api.generate import generate_answer
from guardrails.citation_check import check_citations
from guardrails.prompt_injection import load_prompt_injection_scanner
from retrieval.hybrid_search import connect_db, load_models, retrieve

resources = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the embedding/rerank models and open the DB connection once at
    # startup rather than per request - both models take real time to load,
    # and reloading them on every call would make each request slow.
    embed_model, rerank_model = load_models()
    resources["embed_model"] = embed_model
    resources["rerank_model"] = rerank_model
    resources["scanner"] = load_prompt_injection_scanner()
    resources["conn"] = connect_db()
    yield
    # Langfuse batches trace events and sends them in the background; flush
    # forces any events still queued to be sent before the process exits, so
    # a run right before shutdown isn't silently dropped.
    get_client().flush()
    resources["conn"].close()


app = FastAPI(title="Clinical Evidence Research Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    citations: list[str]
    # Populated by the citation guardrail (guardrails/citation_check.py).
    # Always present, empty when clean - a flag for the caller to display
    # or log, not something that blocks or alters the answer itself.
    uncited_claims: list[str] = []
    fabricated_citations: list[str] = []


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
@observe()
def ask(request: AskRequest):
    cur = resources["conn"].cursor()
    chunks = retrieve(
        cur, resources["embed_model"], resources["rerank_model"], resources["scanner"], request.question
    )
    cur.close()

    answer, citations = generate_answer(request.question, chunks)
    issues = check_citations(answer, chunks)
    return AskResponse(
        answer=answer,
        citations=citations,
        uncited_claims=issues["uncited_sentences"],
        fabricated_citations=issues["fabricated_citations"],
    )
