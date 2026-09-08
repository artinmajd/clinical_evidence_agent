import json
import os

from sentence_transformers import SentenceTransformer

INPUT_PATH = "data/processed/chunks.jsonl"
OUTPUT_PATH = "data/processed/chunks_embedded.jsonl"
MODEL_NAME = "NeuML/pubmedbert-base-embeddings"


def load_chunks(path):
    chunks = []
    with open(path) as f:
        for line in f:
            chunks.append(json.loads(line))
    return chunks


def main():
    chunks = load_chunks(INPUT_PATH)
    texts = [chunk["text"] for chunk in chunks]

    model = SentenceTransformer(MODEL_NAME)
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=32)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding.tolist()
            f.write(json.dumps(chunk) + "\n")

    print(f"Wrote {len(chunks)} embedded chunks to {OUTPUT_PATH}")
    print(f"Embedding dimension: {len(embeddings[0])}")


if __name__ == "__main__":
    main()
