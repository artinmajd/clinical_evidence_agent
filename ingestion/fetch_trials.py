import json
import os
import time

import requests

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
OUTPUT_PATH = "data/raw/trials.jsonl"
TARGET_COUNT = 500
PAGE_SIZE = 1000

PARAMS = {
    "query.cond": "obesity",
    "query.term": "AREA[Phase]PHASE3",
    "filter.overallStatus": "COMPLETED",
    "pageSize": PAGE_SIZE,
}


def fetch_all_studies():
    studies = []
    page_token = None

    while len(studies) < TARGET_COUNT:
        request_params = dict(PARAMS)
        if page_token:
            request_params["pageToken"] = page_token

        response = requests.get(BASE_URL, params=request_params)
        response.raise_for_status()
        data = response.json()

        studies.extend(data["studies"])
        page_token = data.get("nextPageToken")
        if not page_token:
            break

        time.sleep(1)

    return studies[:TARGET_COUNT]


def main():
    studies = fetch_all_studies()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        for study in studies:
            f.write(json.dumps(study) + "\n")

    print(f"Saved {len(studies)} studies to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
