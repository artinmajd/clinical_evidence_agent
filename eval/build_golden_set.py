import json
import random
import re

INPUT_PATH = "data/processed/chunks.jsonl"
OUTPUT_PATH = "eval/golden_set.jsonl"

RANDOM_SEED = 42
NUM_SINGLE_TRIAL_QUESTIONS = 55

# Drug names to look for when grouping trials into aggregate questions. Only
# names that actually show up often enough in the corpus (see MIN_GROUP_SIZE)
# produce a question - this list is just candidates to check for, not a
# guarantee they'll all be used.
CANDIDATE_DRUGS = [
    "semaglutide", "tirzepatide", "liraglutide", "lorcaserin", "naltrexone",
    "bupropion", "orlistat", "phentermine", "topiramate", "setmelanotide",
    "exenatide", "dulaglutide",
]
MIN_GROUP_SIZE = 3


def parse_chunk_text(text):
    """Pull the individual fields back out of the chunk template built by
    processing/prepare_chunks.py."""
    lines = dict(line.split(": ", 1) for line in text.split("\n"))
    return {
        "title": lines.get("Title", ""),
        "conditions": lines.get("Condition(s)", ""),
        "phase": lines.get("Phase", ""),
        "interventions": lines.get("Intervention(s)", ""),
        "primary_outcomes": lines.get("Primary outcome(s)", ""),
    }


def load_chunks():
    chunks = []
    with open(INPUT_PATH) as f:
        for line in f:
            chunk = json.loads(line)
            chunk["fields"] = parse_chunk_text(chunk["text"])
            chunks.append(chunk)
    return chunks


def build_single_trial_questions(chunks, n):
    # Only sample trials that actually have a usable title and primary
    # outcome - a handful of records have gaps in the source API data.
    usable = [c for c in chunks if c["fields"]["title"] and c["fields"]["primary_outcomes"]]
    sample = random.sample(usable, min(n, len(usable)))

    questions = []
    for i, chunk in enumerate(sample, start=1):
        title = chunk["fields"]["title"]
        questions.append({
            "id": f"single_{i:03d}",
            "type": "single_trial",
            "question": f'What was the primary outcome measure in the trial "{title}"?',
            "expected_citations": [chunk["nct_id"]],
            "reference_answer": chunk["fields"]["primary_outcomes"],
        })
    return questions


def build_aggregate_questions(chunks):
    questions = []
    for i, drug in enumerate(CANDIDATE_DRUGS, start=1):
        pattern = re.compile(re.escape(drug), re.IGNORECASE)
        matches = [c for c in chunks if pattern.search(c["fields"]["interventions"])]
        if len(matches) < MIN_GROUP_SIZE:
            continue
        questions.append({
            "id": f"agg_{i:03d}",
            "type": "aggregate",
            "question": f"What were the primary outcome measures across phase 3 trials testing {drug}?",
            "expected_citations": [c["nct_id"] for c in matches],
            "reference_answer": None,
        })
    return questions


def main():
    random.seed(RANDOM_SEED)
    chunks = load_chunks()

    golden_set = build_single_trial_questions(chunks, NUM_SINGLE_TRIAL_QUESTIONS)
    golden_set += build_aggregate_questions(chunks)

    with open(OUTPUT_PATH, "w") as f:
        for item in golden_set:
            f.write(json.dumps(item) + "\n")

    single_count = sum(1 for q in golden_set if q["type"] == "single_trial")
    agg_count = sum(1 for q in golden_set if q["type"] == "aggregate")
    print(f"Wrote {len(golden_set)} questions to {OUTPUT_PATH} ({single_count} single-trial, {agg_count} aggregate)")


if __name__ == "__main__":
    main()
