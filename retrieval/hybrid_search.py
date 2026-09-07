import os

import psycopg2
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()

MODEL_NAME = "NeuML/pubmedbert-base-embeddings"
TOP_K = 10
RRF_K = 60

CONNECTION = {
    "host": os.environ["SUPABASE_DB_HOST"],
    "port": os.environ.get("SUPABASE_DB_PORT", "5432"),
    "dbname": os.environ.get("SUPABASE_DB_NAME", "postgres"),
    "user": os.environ.get("SUPABASE_DB_USER", "postgres"),
    "password": os.environ["SUPABASE_DB_PASSWORD"],
}


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


def main():
    question = "What were the primary endpoints in phase 3 obesity trials?"

    model = SentenceTransformer(MODEL_NAME)
    query_embedding = model.encode(question)

    conn = psycopg2.connect(**CONNECTION)
    register_vector(conn)
    cur = conn.cursor()

    semantic_ids = semantic_search(cur, query_embedding, TOP_K)
    keyword_ids = keyword_search(cur, question, TOP_K)
    fused = reciprocal_rank_fusion([semantic_ids, keyword_ids])

    print(f"Question: {question}\n")
    print(f"Semantic hits: {len(semantic_ids)}, keyword hits: {len(keyword_ids)}\n")

    for chunk_id, score in fused[:TOP_K]:
        nct_id, chunk_text = fetch_chunk(cur, chunk_id)
        print(f"[{score:.4f}] {nct_id}")
        print(chunk_text.splitlines()[0])
        print()

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
