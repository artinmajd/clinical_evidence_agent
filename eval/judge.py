import json

from langfuse.openai import OpenAI

# Deliberately a stronger/more expensive model than the one being judged
# (gpt-4o-mini in api/generate.py). A judge that's no more capable than the
# system it's grading is more likely to miss the same mistakes the system
# itself would make.
JUDGE_MODEL = "gpt-4o"

JUDGE_SYSTEM_PROMPT = (
    "You are grading a RAG system's answer against the context it was given. "
    "Score two things, based ONLY on whether the answer is consistent with "
    "the provided context - not on your own outside knowledge of the topic:\n"
    "- faithfulness (0.0-1.0): what fraction of the claims in the answer are "
    "actually supported by the context. 1.0 means every claim traces back to "
    "the context; 0.0 means the answer is entirely unsupported or fabricated.\n"
    "- completeness (0.0-1.0): how well the answer addresses the question, "
    "given what the context actually contains. 1.0 means it fully answers "
    "the question; lower scores mean it missed relevant information that was "
    "available in the context, or dodged the question.\n"
    'Respond with a JSON object: {"faithfulness": <float>, '
    '"completeness": <float>, "rationale": "<one sentence>"}.'
)

client = OpenAI()


def judge_answer(question, context, answer):
    """Score a generated answer against the context it was given. Returns a
    dict with faithfulness, completeness, and a short rationale."""
    user_prompt = (
        f"Question: {question}\n\n"
        f"Context provided to the system:\n{context}\n\n"
        f"System's answer:\n{answer}"
    )
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    return json.loads(response.choices[0].message.content)
