import re

from openai import OpenAI

GENERATION_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = (
    "You are a clinical research assistant. Answer the question using ONLY "
    "the trial excerpts provided below - do not use outside knowledge. Cite "
    "the NCT ID in brackets after every claim you make, e.g. [NCT00395135]. "
    "If the excerpts don't contain enough information to answer, say so "
    "explicitly instead of guessing."
)

client = OpenAI()


def build_context(chunks):
    return "\n\n".join(f"[{nct_id}]\n{chunk_text}" for _, nct_id, chunk_text, _ in chunks)


def generate_answer(question, chunks):
    """Call the LLM with the retrieved chunks as grounding context, and
    return (answer_text, citations). Citations are the NCT IDs the model
    actually cited in its answer, not just the ones it was given - a model
    that ignores a retrieved chunk shouldn't get credit for citing it."""
    context = build_context(chunks)
    user_prompt = f"Trial excerpts:\n\n{context}\n\nQuestion: {question}"

    response = client.chat.completions.create(
        model=GENERATION_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    answer = response.choices[0].message.content

    citations = sorted(set(re.findall(r"NCT\d+", answer)))
    return answer, citations
