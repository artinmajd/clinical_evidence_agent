"""
Step 1 of Phase 1: explore the ClinicalTrials.gov v2 API.

Goal: see the real shape of a study record before writing any real
ingestion pipeline around assumptions. This script is disposable, it's not
part of the final pipeline, just a way to look at real data.
"""

import json
import requests

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"

# query.cond          -> narrows to a condition/disease
# query.term          -> general search; used here for the Essie expression
#                        "AREA[Phase]PHASE3", since there's no dedicated
#                        filter.phase parameter (learned the hard way)
# filter.overallStatus -> only completed trials (we want real outcomes,
#                        not ones still recruiting)
# pageSize             -> how many studies to fetch in this one request
params = {
    "query.cond": "obesity",
    "query.term": "AREA[Phase]PHASE3",
    "filter.overallStatus": "COMPLETED",
    "pageSize": 20,
}

response = requests.get(BASE_URL, params=params)
response.raise_for_status()  # fail loudly if the request didn't succeed
data = response.json()

studies = data["studies"]
print(f"Fetched {len(studies)} studies\n")

# --- Look at the first study's key modules ---
first = studies[0]["protocolSection"]

modules_to_inspect = [
    "identificationModule",
    "conditionsModule",
    "designModule",
    "armsInterventionsModule",
    "outcomesModule",
]

for module_name in modules_to_inspect:
    print(f"--- {module_name} ---")
    print(json.dumps(first.get(module_name, {}), indent=2))
    print()

# --- Count how many of the fetched studies actually have results ---
with_results = sum(1 for study in studies if study.get("hasResults"))
print(f"{with_results} out of {len(studies)} studies have results")
