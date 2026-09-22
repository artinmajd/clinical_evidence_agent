import os

# Must run before sentence_transformers/llm_guard (and the HF tokenizers
# library they both pull in) get imported anywhere in this process.
# TOKENIZERS_PARALLELISM=false avoids a well-known HuggingFace deadlock/
# slowdown when multiple tokenizers exist in one process (we load three
# transformer models here); capping thread count stops all three models
# from each independently grabbing every CPU core and thrashing against
# each other - both changes came out of a real, reproducible system
# slowdown while testing the guardrail (see CHALLENGES.md).
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch

torch.set_num_threads(2)

import psycopg2
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from langfuse import observe
from sentence_transformers import CrossEncoder, SentenceTransformer

from guardrails.prompt_injection import load_prompt_injection_scanner, scan_chunks

load_dotenv()

MODEL_NAME = "NeuML/pubmedbert-base-embeddings"
RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
TOP_K = 10
RRF_K = 60

CONNECTION = {
    "host": os.environ["SUPABASE_DB_HOST"],
    "port": os.environ.get("SUPABASE_DB_PORT", "5432"),
    "dbname": os.environ.get("SUPABASE_DB_NAME", "postgres"),
    "user": os.environ.get("SUPABASE_DB_USER", "postgres"),
    "password": os.environ["SUPABASE_DB_PASSWORD"],
}


def load_models():
    """Load the embedding and reranking models once, so callers (the API in
    particular) don't pay model-load latency on every request.

    Forced onto CPU explicitly (device="cpu") rather than letting
    sentence-transformers auto-detect and default to Apple Silicon's MPS
    (Metal) backend. This matches the project plan's stated architecture
    (CPU-only through Phase 5, GPU reserved for the optional Phase 6
    benchmark) - and stopped being optional after a real incident: with
    three transformer models (these two, plus the prompt-injection
    scanner) all auto-defaulting onto MPS's shared unified memory, a
    single query pushed PyTorch's MPS allocator to a 20+ GiB ceiling,
    which is a plausible contributor to a kernel panic (watchdog timeout)
    on the machine this runs on. CPU is measurably slower per call, but
    this corpus and query volume are small enough that the latency is a
    non-issue, per the plan's own cost/latency tradeoff."""
    return (
        SentenceTransformer(MODEL_NAME, device="cpu"),
        CrossEncoder(RERANK_MODEL_NAME, device="cpu"),
    )


def connect_db():
    conn = psycopg2.connect(**CONNECTION)
    register_vector(conn)
    return conn


def semantic_search(cur, query_embedding, top_k):
    cur.execute(
        """
        select id
        from trial_chunks
        order by embedding <=> %s::vector
        limit %s
        """,
        (query_embedding, top_k),
    )
    return [row[0] for row in cur.fetchall()]


def keyword_search(cur, query_text, top_k):
    # OR the words together instead of the default AND, so a chunk matching
    # some meaningful words still surfaces rather than requiring every word
    # (after stemming) to be present in the same row.
    or_query_text = " or ".join(query_text.split())
    cur.execute(
        """
        select id
        from trial_chunks
        where chunk_text_tsv @@ websearch_to_tsquery('english', %s)
        order by ts_rank(chunk_text_tsv, websearch_to_tsquery('english', %s)) desc
        limit %s
        """,
        (or_query_text, or_query_text, top_k),
    )
    return [row[0] for row in cur.fetchall()]


def reciprocal_rank_fusion(ranked_lists, k=RRF_K):
    scores = {}
    for ranked_list in ranked_lists:
        for rank, item_id in enumerate(ranked_list, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


def fetch_chunk(cur, chunk_id):
    cur.execute(
        "select nct_id, chunk_text from trial_chunks where id = %s",
        (chunk_id,),
    )
    return cur.fetchone()


def rerank(model, query, candidates):
    # A cross-encoder reads the query and a candidate together and outputs a
    # single relevance score, unlike the bi-encoder above which embeds them
    # separately. It's more accurate but far slower, so it only runs on the
    # small shortlist RRF already narrowed down, not the full corpus.
    pairs = [(query, chunk_text) for _, _, chunk_text in candidates]
    scores = model.predict(pairs)
    ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
    # Cast to plain Python float: CrossEncoder returns numpy.float32, which
    # LangGraph's Postgres checkpointer can't msgpack-serialize.
    return [
        (chunk_id, nct_id, chunk_text, float(score))
        for (chunk_id, nct_id, chunk_text), score in ranked
    ]


# capture_input/capture_output=False: by default @observe() tries to
# serialize every argument and the return value for its trace log. This
# function's arguments include three loaded transformer model objects and a
# live database cursor, none of which are meaningfully serializable - with
# all of them turned on at once, capturing them was reliably choking (long
# hangs, and multiple real out-of-memory kills - see CHALLENGES.md) rather
# than just adding "overhead" as Langfuse's own docs warn. Disabling this
# only turns off automatic capture; if we want the question/answer visible
# in traces later, that should be added back deliberately with a manual,
# lightweight langfuse_context update - not by re-enabling blanket capture
# of every argument this function happens to take.
@observe(capture_input=False, capture_output=False)
def retrieve(cur, embed_model, rerank_model, scanner, question, top_k=TOP_K):
    """Full retrieval pipeline: hybrid search (semantic + keyword), RRF
    fusion, cross-encoder rerank, then a prompt-injection scan that drops
    any chunk trying to smuggle instructions to the LLM. Returns the
    surviving top_k results as (chunk_id, nct_id, chunk_text, rerank_score)
    tuples, best first - possibly fewer than top_k if the scan dropped any."""
    query_embedding = embed_model.encode(question)
    semantic_ids = semantic_search(cur, query_embedding, top_k)
    keyword_ids = keyword_search(cur, question, top_k)
    fused = reciprocal_rank_fusion([semantic_ids, keyword_ids])

    candidates = []
    for chunk_id, _ in fused:
        nct_id, chunk_text = fetch_chunk(cur, chunk_id)
        candidates.append((chunk_id, nct_id, chunk_text))

    reranked = rerank(rerank_model, question, candidates)[:top_k]
    return scan_chunks(scanner, reranked)


def main():
    question = "What were the primary endpoints in phase 3 obesity trials?"

    embed_model, rerank_model = load_models()
    scanner = load_prompt_injection_scanner()
    conn = connect_db()
    cur = conn.cursor()

    results = retrieve(cur, embed_model, rerank_model, scanner, question)

    print(f"Question: {question}\n")
    for chunk_id, nct_id, chunk_text, score in results:
        print(f"[{score:.4f}] {nct_id}")
        print(chunk_text.splitlines()[0])
        print()

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
