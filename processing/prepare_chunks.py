import json
import os

INPUT_PATH = "data/raw/trials.jsonl"
OUTPUT_PATH = "data/processed/chunks.jsonl"


def build_chunk_text(study):
    protocol = study["protocolSection"]

    identification = protocol.get("identificationModule", {})
    conditions = protocol.get("conditionsModule", {})
    design = protocol.get("designModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    outcomes = protocol.get("outcomesModule", {})

    title = identification.get("briefTitle", "")
    condition_list = conditions.get("conditions", [])
    phases = design.get("phases", [])
    intervention_names = [i.get("name", "") for i in arms.get("interventions", [])]
    primary_outcomes = [o.get("measure", "") for o in outcomes.get("primaryOutcomes", [])]

    lines = [
        f"Title: {title}",
        f"Condition(s): {', '.join(condition_list)}",
        f"Phase: {', '.join(phases)}",
        f"Intervention(s): {', '.join(intervention_names)}",
        f"Primary outcome(s): {'; '.join(primary_outcomes)}",
    ]
    return "\n".join(lines)


def main():
    chunks = []

    with open(INPUT_PATH) as f:
        for line in f:
            study = json.loads(line)
            nct_id = study["protocolSection"]["identificationModule"]["nctId"]

            chunks.append({
                "nct_id": nct_id,
                "text": build_chunk_text(study),
                "phases": study["protocolSection"].get("designModule", {}).get("phases", []),
                "conditions": study["protocolSection"].get("conditionsModule", {}).get("conditions", []),
                "has_results": study.get("hasResults", False),
            })

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk) + "\n")

    print(f"Wrote {len(chunks)} chunks to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
