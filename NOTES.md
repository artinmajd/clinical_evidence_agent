# Concept notes

Short explanations of concepts as we hit them, written so they make sense on
a re-read weeks later without me re-explaining from scratch.

## REST APIs, and ClinicalTrials.gov v2 specifically

A REST API is just a web server that answers HTTP requests with JSON instead
of HTML. "GET https://clinicaltrials.gov/api/v2/studies?query.cond=..." is a
regular URL; the "query parameters" after the `?` tell the server how to
filter. No auth needed for normal use.

Query parameters we care about for this project:
- `query.cond` — searches the disease/condition field specifically (narrower,
  more precise than a general search)
- `query.term` — general full-text search across the whole study
- `filter.phase` — PHASE1 / PHASE2 / PHASE3 / PHASE4
- `filter.overallStatus` — e.g. COMPLETED (we want finished trials with real
  outcomes, not ones still recruiting)
- `pageSize` — up to 1000 per page; `pageToken` pages through more

Each study in the response is a big nested JSON object. The two sections
that matter:

**protocolSection** (always present) — the trial's design, broken into
sub-modules:
- `identificationModule` — NCT ID, title
- `descriptionModule` — brief summary, detailed description
- `conditionsModule` — the disease(s) studied
- `designModule` — phase, enrollment size
- `armsInterventionsModule` — what was actually tested (drug, dose, control)
- `outcomesModule` — the primary/secondary outcome measures *definitions*
  (what was measured, not the actual numeric result)

**resultsSection** (only present if the trial reported results) — the actual
numbers:
- `outcomeMeasuresModule` — the quantitative results
- `adverseEventsModule` — safety data
- (also participantFlowModule, baselineCharacteristicsModule)

This matters for later: a question like "what were the primary endpoints"
can be answered from protocolSection alone, but "what was the actual effect
size" needs resultsSection, which not every trial has. Worth checking how
many trials in our corpus actually have results before promising the agent
can answer outcome-number questions for all of them.
