import argparse
import json
import random
import statistics
import sys

from dotenv import load_dotenv
from langfuse import get_client, observe

# Load .env before importing modules that read credentials at import time
# (e.g. api.generate and eval.judge construct OpenAI() using OPENAI_API_KEY).
load_dotenv()

from api.generate import build_context, generate_answer
from eval.judge import judge_answer
from retrieval.hybrid_search import connect_db, load_models, retrieve

GOLDEN_SET_PATH = "eval/golden_set.jsonl"
langfuse = get_client()
RESULTS_PATH = "eval/last_run.json"
DEFAULT_LIMIT = 15
DEFAULT_MIN_FAITHFULNESS = 0.8
SAMPLE_SEED = 7


def load_golden_set():
    with open(GOLDEN_SET_PATH) as f:
        return [json.loads(line) for line in f]


def select_subset(golden_set, limit, seed=SAMPLE_SEED):
    """Sample a reduced-size subset that keeps roughly the same mix of
    question types as the full golden set, instead of just taking the first
    N items - the file lists all single_trial questions before the
    aggregate ones, so a plain slice would silently skip the harder
    aggregate questions entirely whenever limit < 55."""
    if limit >= len(golden_set):
        return golden_set

    by_type = {}
    for item in golden_set:
        by_type.setdefault(item["type"], []).append(item)

    rng = random.Random(seed)
    subset = []
    for items in by_type.values():
        share = max(1, round(limit * len(items) / len(golden_set)))
        subset.extend(rng.sample(items, min(share, len(items))))

    return subset[:limit]


def citation_metrics(actual_citations, expected_citations):
    # Precision: of what the system cited, how much was actually correct.
    # Hit: did it get at least one right citation at all. We don't score
    # recall against the full expected set for aggregate questions, since
    # retrieval only ever returns a top-k shortlist, not every matching
    # trial in the corpus - see the golden set builder's notes.
    actual = set(actual_citations)
    expected = set(expected_citations)
    overlap = actual & expected
    precision = len(overlap) / len(actual) if actual else 0.0
    hit = 1.0 if overlap else 0.0
    return {"citation_precision": precision, "citation_hit": hit}


@observe()
def evaluate_question(item, embed_model, rerank_model, conn):
    cur = conn.cursor()
    chunks = retrieve(cur, embed_model, rerank_model, item["question"])
    cur.close()

    answer, citations = generate_answer(item["question"], chunks)
    context = build_context(chunks)
    judged = judge_answer(item["question"], context, answer)
    metrics = citation_metrics(citations, item["expected_citations"])

    # Attach the eval scores to this question's trace, so it's visible and
    # filterable in the Langfuse dashboard, not just in a local JSON file.
    langfuse.score_current_trace(name="faithfulness", value=judged["faithfulness"])
    langfuse.score_current_trace(name="completeness", value=judged["completeness"])
    langfuse.score_current_trace(name="citation_precision", value=metrics["citation_precision"])

    return {
        "id": item["id"],
        "type": item["type"],
        "question": item["question"],
        "answer": answer,
        "citations": citations,
        "expected_citations": item["expected_citations"],
        **metrics,
        **judged,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"Number of golden-set questions to run (default: {DEFAULT_LIMIT}). Ignored with --all.",
    )
    parser.add_argument("--all", action="store_true", help="Run the full golden set instead of --limit")
    parser.add_argument(
        "--min-faithfulness", type=float, default=DEFAULT_MIN_FAITHFULNESS,
        help=f"Exit with a non-zero status if median faithfulness drops below this (default: {DEFAULT_MIN_FAITHFULNESS}).",
    )
    args = parser.parse_args()

    golden_set = load_golden_set()
    if not args.all:
        golden_set = select_subset(golden_set, args.limit)

    embed_model, rerank_model = load_models()
    conn = connect_db()

    results = []
    for item in golden_set:
        print(f"Evaluating {item['id']}...")
        results.append(evaluate_question(item, embed_model, rerank_model, conn))

    conn.close()
    langfuse.flush()

    faithfulness_scores = [r["faithfulness"] for r in results]
    completeness_scores = [r["completeness"] for r in results]
    citation_hits = [r["citation_hit"] for r in results]

    print(f"\nRan {len(results)} questions")
    print(f"Median faithfulness:  {statistics.median(faithfulness_scores):.2f}")
    print(f"Median completeness:  {statistics.median(completeness_scores):.2f}")
    print(f"Citation hit rate:    {sum(citation_hits) / len(citation_hits):.2%}")

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results written to {RESULTS_PATH}")

    median_faithfulness = statistics.median(faithfulness_scores)
    if median_faithfulness < args.min_faithfulness:
        print(
            f"\nFAIL: median faithfulness {median_faithfulness:.2f} is below "
            f"the required {args.min_faithfulness:.2f}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
