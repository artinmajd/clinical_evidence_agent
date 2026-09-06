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

## Debugging note: `filter.phase` is not real (found 2026-09-06)

Several blog posts and even "official-looking" third-party API reference
docs claim `filter.phase` exists. It does not; the live API rejects it with
`` `filter.phase` is unknown parameter``. Lesson: for any API, trust the
API's own response over secondhand docs, especially anything that reads
like it was AI-generated and never actually run against the live endpoint.

**What actually works:** phase filtering goes through the Essie search
syntax, embedded in `query.term`:
```
query.term=AREA[Phase]PHASE3
```
(URL-encoded: `AREA%5BPhase%5DPHASE3`)

**Important nuance:** this matches trials where PHASE3 appears anywhere in
the `phases` array, not an exact match. A combined Phase 2/3 trial
(`"phases": ["PHASE2", "PHASE3"]`) matches too. Decide later whether the
corpus should include those or only pure single-phase-3 trials (can filter
client-side on the exact array value either way).

**Handy field:** each study has a top-level `"hasResults": true/false` flag,
so no need to check for the presence of `resultsSection` manually.

Neither this session's cloud sandbox nor a shell on Artin's own Mac could
reach clinicaltrials.gov directly (both got no connection at all) - some
environments just don't have outbound access to arbitrary domains. Browser
requests work fine. Worth remembering if a script run from the terminal
later mysteriously can't connect either.

## Concept: clinical trial phases and endpoints

- **Phase 1** — small (dozens), safety/dosage focused, not testing whether it works yet.
- **Phase 2** — bigger (dozens to ~hundreds), starts testing effectiveness, still watching safety.
- **Phase 3** — large (hundreds to thousands), randomized controlled trial vs. placebo/standard
  treatment. This is the one regulators use to approve a drug, and the one this project cares
  about most when someone asks "what were the phase 3 results."
- **Phase 4** — post-approval, monitors long-term effects in the general population.
- Combined labels like `["PHASE2", "PHASE3"]` are real: some trials deliberately blend the two
  ("seamless" design) instead of running them separately.

**Endpoint / outcome measure** = the specific thing a trial was designed to measure to judge
success (e.g. "change in blood glucose at 6 months"). **Primary** endpoint = the main one the
trial is judged on. **Secondary** endpoints = additional things measured alongside it. Lives in
`outcomesModule.primaryOutcomes` / `.secondaryOutcomes` in the API response.
