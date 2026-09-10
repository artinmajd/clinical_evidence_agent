import argparse
import json
import statistics

from langfuse import get_client, observe

from api.generate import build_context, generate_answer
from eval.judge import judge_answer
from retrieval.hybrid_search import connect_db, load_models, retrieve

GOLDEN_SET_PATH = "eval/golden_set.jsonl"
langfuse = get_client()
RESULTS_PATH = "eval/last_run.json"
DEFAULT_LIMIT = 15


def load_golden_set():
    with open(GOLDEN_SET_PATH) as f:
        return [json.loads(line) for line in f]


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
    args = parser.parse_args()

    golden_set = load_golden_set()
    if not args.all:
        golden_set = golden_set[: args.limit]

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


if __name__ == "__main__":
    main()
