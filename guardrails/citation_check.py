"""Output guardrail: catches claims the model makes without a verifiable
citation.

generate_answer() instructs the model to cite an NCT ID after every claim,
and it mostly does - but "the model wrote a citation" and "that citation
can be trusted" are different guarantees. Two independent failure modes,
both checked here:

- an uncited claim: a sentence with no NCT ID citation at all.
- a fabricated citation: a sentence citing an NCT ID that was never
  actually among the chunks retrieved for this question. These models
  have seen huge numbers of real ClinicalTrials.gov IDs during training,
  so under instruction pressure to "always cite something" they can
  produce a plausible-looking ID from memory instead of admitting a claim
  isn't supported. A citation like this looks *more* trustworthy than an
  uncited claim, not less - which is exactly what makes it worth checking
  for separately rather than assuming "has a citation" is good enough.

This is deliberately a fast, deterministic, free check, not an LLM call.
eval/judge.py already does a much more thorough (and expensive) semantic
faithfulness check with gpt-4o, but only offline against the golden set in
CI. This one has to run on every live request, so it trades precision for
being essentially instant - see CHALLENGES.md/NOTES.md for why "flag,
don't block" was chosen as this guardrail's behavior.
"""

import re

CITATION_PATTERN = re.compile(r"NCT\d+")

# Very short sentences are usually lead-ins/fragments ("Based on the
# trials:"), not standalone claims - flagging those as "uncited" would
# mostly be noise. This is a blunt length heuristic, not real sentence
# understanding; false positives/negatives are expected and acceptable
# since this guardrail only ever flags, never blocks or rewrites anything.
MIN_CLAIM_LENGTH = 20


def split_sentences(text):
    # A simple heuristic split, not a real sentence tokenizer: break after
    # a ./!/? that's followed by whitespace, as long as that punctuation
    # isn't immediately preceded by a digit - which almost always means
    # it's a numbered-list marker ("1.", "2.") rather than a real
    # sentence end. Without that exclusion, a numbered-list answer (which
    # is exactly what aggregate questions tend to produce) gets its lead-in
    # text split off from its own citation, flagged as an uncited claim
    # that doesn't actually exist - a real false positive seen in testing,
    # not a hypothetical one. Still misses some other cases (e.g. "e.g."
    # followed by a space looks like a sentence end) - good enough for a
    # check whose only job is surfacing things for a human to glance at.
    return [s.strip() for s in re.split(r"(?<=[^0-9][.!?])\s+", text.strip()) if s.strip()]


def check_citations(answer, chunks):
    """Check a generated answer against the chunks it was actually given.

    Returns a dict: {"uncited_sentences": [...], "fabricated_citations":
    [...], "has_issues": bool}. uncited_sentences holds the offending
    sentence text (useful for a human reviewing the flag); fabricated_
    citations holds just the bad NCT IDs."""
    grounded_ids = {nct_id for _, nct_id, _, _ in chunks}

    uncited_sentences = []
    cited_ids = set()
    for sentence in split_sentences(answer):
        ids_in_sentence = CITATION_PATTERN.findall(sentence)
        cited_ids.update(ids_in_sentence)
        if not ids_in_sentence and len(sentence) >= MIN_CLAIM_LENGTH:
            uncited_sentences.append(sentence)

    fabricated_citations = sorted(cited_ids - grounded_ids)

    return {
        "uncited_sentences": uncited_sentences,
        "fabricated_citations": fabricated_citations,
        "has_issues": bool(uncited_sentences or fabricated_citations),
    }
