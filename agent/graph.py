"""LangGraph state graph wrapping the existing retrieval/generation pipeline.

Phase 3, step 1: structure only (plan -> retrieve -> extract -> self_check ->
respond), reusing the existing retrieve()/generate_answer() functions.

Phase 3, step 2: Postgres-backed checkpointing. After every node runs, the
graph's state gets saved to Postgres under a "thread_id" - invoking again
with the same thread_id resumes that run from its last saved state instead
of starting over.

Phase 3, step 3: a human-approval interrupt(). When self_check flags an
answer as ungrounded (no citations), the graph now routes to a
human_review node instead of going straight to respond. That node calls
interrupt(), which pauses the graph, saves its state via the checkpointer,
and hands a payload to whoever is calling invoke(). Execution only
continues once someone resumes it with Command(resume=...). This is only
possible because of step 2's checkpointing - the pause can last arbitrarily
long because the state isn't sitting in memory, it's saved in Postgres.

Note: this uses a *separate* Postgres connection/driver (psycopg, v3) from
the one retrieval/hybrid_search.py uses (psycopg2) for pgvector search.
Both connect to the same database; they just don't share a connection.
"""

import os
from typing import TypedDict

from dotenv import load_dotenv

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

load_dotenv()

from api.generate import generate_answer
from guardrails.prompt_injection import load_prompt_injection_scanner
from retrieval.hybrid_search import connect_db, load_models, retrieve

DB_URI = (
    f"postgresql://{os.environ.get('SUPABASE_DB_USER', 'postgres')}:"
    f"{os.environ['SUPABASE_DB_PASSWORD']}@{os.environ['SUPABASE_DB_HOST']}:"
    f"{os.environ.get('SUPABASE_DB_PORT', '5432')}/"
    f"{os.environ.get('SUPABASE_DB_NAME', 'postgres')}"
)


class AgentState(TypedDict):
    question: str
    chunks: list
    answer: str
    citations: list
    needs_review: bool


def build_graph(embed_model, rerank_model, scanner, conn, checkpointer=None):
    """Compile the agent graph, with the heavy resources (models, DB
    connection) bound via closures rather than stored in state - state gets
    checkpointed/serialized, and these objects aren't serializable."""

    def plan(state: AgentState) -> dict:
        # Placeholder for now: later this is where query rewriting or
        # single-trial vs. aggregate classification would happen.
        return {}

    def retrieve_node(state: AgentState) -> dict:
        cur = conn.cursor()
        chunks = retrieve(cur, embed_model, rerank_model, scanner, state["question"])
        cur.close()
        return {"chunks": chunks}

    def extract_node(state: AgentState) -> dict:
        answer, citations = generate_answer(state["question"], state["chunks"])
        return {"answer": answer, "citations": citations}

    def self_check_node(state: AgentState) -> dict:
        # Minimal groundedness check: an answer with zero citations is
        # flagged for human review instead of being returned as-is.
        needs_review = len(state["citations"]) == 0
        return {"needs_review": needs_review}

    def human_review_node(state: AgentState) -> dict:
        # Pauses here. The dict passed to interrupt() is what the caller
        # sees while the graph is paused; whatever the caller later passes
        # to Command(resume=...) becomes this function's return value.
        decision = interrupt({
            "reason": "No citations found - answer may not be grounded in the corpus.",
            "question": state["question"],
            "draft_answer": state["answer"],
        })
        return {"answer": decision["answer"]}

    def respond_node(state: AgentState) -> dict:
        # Terminal node - state already holds everything the caller needs.
        return {}

    def route_after_self_check(state: AgentState) -> str:
        return "human_review" if state["needs_review"] else "respond"

    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("extract", extract_node)
    graph.add_node("self_check", self_check_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("respond", respond_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "retrieve")
    graph.add_edge("retrieve", "extract")
    graph.add_edge("extract", "self_check")
    graph.add_conditional_edges(
        "self_check",
        route_after_self_check,
        {"human_review": "human_review", "respond": "respond"},
    )
    graph.add_edge("human_review", "respond")
    graph.add_edge("respond", END)

    return graph.compile(checkpointer=checkpointer)


def run_question(app, checkpointer, question, thread_id):
    """Run one question through the graph, pausing for a real terminal
    input if the graph interrupts for human review.

    Checkpointing exists to make an in-flight pause survivable, not to
    serve as a permanent record - Langfuse (Phase 2) already traces every
    run for that. So once this thread reaches a final answer, its
    checkpoint rows have no further purpose and are deleted immediately,
    keeping the checkpoint tables holding only threads that are still
    genuinely paused/in-flight."""
    config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke({"question": question}, config=config)

    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        print(f"\n[PAUSED for human review] {question}")
        print(f"Reason: {payload['reason']}")
        print(f"Draft answer: {payload['draft_answer']}\n")

        decision = input("Approve this draft as-is? (y/n): ").strip().lower()
        if decision == "y":
            final_answer = payload["draft_answer"]
        else:
            final_answer = input("Enter the corrected answer to use instead: ")

        result = app.invoke(Command(resume={"answer": final_answer}), config=config)
        print(f"\n[RESUMED] Final answer: {result['answer']}")
    else:
        print(f"\n[No review needed] {question}")
        print(f"Answer: {result['answer']}")
        print(f"Citations: {result['citations']}")

    checkpointer.delete_thread(thread_id)


def main():
    embed_model, rerank_model = load_models()
    scanner = load_prompt_injection_scanner()
    conn = connect_db()

    with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        checkpointer.setup()
        app = build_graph(embed_model, rerank_model, scanner, conn, checkpointer=checkpointer)

        # A well-covered question: expect this to sail straight through
        # respond without ever touching human_review.
        run_question(
            app,
            checkpointer,
            "What were the primary endpoints of the trials studying semaglutide?",
            thread_id="demo-good",
        )

        # A question outside the corpus (this project only has obesity/GLP-1
        # trials): expect zero citations, which should trigger the
        # human_review interrupt.
        run_question(
            app,
            checkpointer,
            "What is the standard treatment protocol for the common cold?",
            thread_id="demo-risky",
        )

    conn.close()


if __name__ == "__main__":
    main()
