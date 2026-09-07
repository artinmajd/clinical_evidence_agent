import json
import os

import psycopg2
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector

load_dotenv()

INPUT_PATH = "data/processed/chunks_embedded.jsonl"

CONNECTION = {
    "host": os.environ["SUPABASE_DB_HOST"],
    "port": os.environ.get("SUPABASE_DB_PORT", "5432"),
    "dbname": os.environ.get("SUPABASE_DB_NAME", "postgres"),
    "user": os.environ.get("SUPABASE_DB_USER", "postgres"),
    "password": os.environ["SUPABASE_DB_PASSWORD"],
}


def load_chunks(path):
    chunks = []
    with open(path) as f:
        for line in f:
            chunks.append(json.loads(line))
    return chunks


def main():
    chunks = load_chunks(INPUT_PATH)

    conn = psycopg2.connect(**CONNECTION)
    register_vector(conn)
    cur = conn.cursor()

    cur.execute("delete from trial_chunks")

    for chunk in chunks:
        cur.execute(
            """
            insert into trial_chunks (nct_id, chunk_text, phases, conditions, has_results, embedding)
            values (%s, %s, %s, %s, %s, %s)
            """,
            (
                chunk["nct_id"],
                chunk["text"],
                chunk["phases"],
                chunk["conditions"],
                chunk["has_results"],
                chunk["embedding"],
            ),
        )

    conn.commit()
    cur.close()
    conn.close()

    print(f"Loaded {len(chunks)} chunks into trial_chunks")


if __name__ == "__main__":
    main()
