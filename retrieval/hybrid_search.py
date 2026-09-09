import os

import psycopg2
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from langfuse import observe
from sentence_transformers import CrossEncoder, SentenceTransformer

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
    particular) don't pay model-load latency on every request."""
    return SentenceTransformer(MODEL_NAME), CrossEncoder(RERANK_MODEL_NAME)


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
    return [
        (chunk_id, nct_id, chunk_text, score)
        for (chunk_id, nct_id, chunk_text), score in ranked
    ]


@observe()
def retrieve(cur, embed_model, rerank_model, question, top_k=TOP_K):
    """Full retrieval pipeline: hybrid search (semantic + keyword), RRF
    fusion, then cross-encoder rerank. Returns the top_k results as
    (chunk_id, nct_id, chunk_text, rerank_score) tuples, best first."""
    query_embedding = embed_model.encode(question)
    semantic_ids = semantic_search(cur, query_embedding, top_k)
    keyword_ids = keyword_search(cur, question, top_k)
    fused = reciprocal_rank_fusion([semantic_ids, keyword_ids])

    candidates = []
    for chunk_id, _ in fused:
        nct_id, chunk_text = fetch_chunk(cur, chunk_id)
        candidates.append((chunk_id, nct_id, chunk_text))

    return rerank(rerank_model, question, candidates)[:top_k]


def main():
    question = "What were the primary endpoints in phase 3 obesity trials?"

    embed_model, rerank_model = load_models()
    conn = connect_db()
    cur = conn.cursor()

    results = retrieve(cur, embed_model, rerank_model, question)

    print(f"Question: {question}\n")
    for chunk_id, nct_id, chunk_text, score in results:
        print(f"[{score:.4f}] {nct_id}")
        print(chunk_text.splitlines()[0])
        print()

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
