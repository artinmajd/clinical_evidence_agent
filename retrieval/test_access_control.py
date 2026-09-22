"""Standalone verification for Phase 4 Step 3 - proves the row-level
permission filter actually holds, without spending a single OpenAI call.
Access control is entirely a retrieval/database concern (does the right
SQL come back for the right role); it has nothing to do with answer
generation, so this doesn't need generate_answer(), judge_answer(), or
any LLM at all - unlike eval/run_eval.py, this is free to run as often as
you like.

Run after db/migrate_permission_groups.py has tagged the table:
    python -m retrieval.test_access_control
"""

from dotenv import load_dotenv

load_dotenv()

from guardrails.access_control import allowed_groups
from guardrails.prompt_injection import load_prompt_injection_scanner
from retrieval.hybrid_search import connect_db, load_models, retrieve

QUESTION = "What were the primary endpoints in phase 3 obesity trials?"


def permission_group_of(cur, nct_id):
    cur.execute(
        "select permission_group from trial_chunks where nct_id = %s limit 1",
        (nct_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def main():
    embed_model, rerank_model = load_models()
    scanner = load_prompt_injection_scanner()
    conn = connect_db()
    cur = conn.cursor()

    failures = []

    for role in ("researcher", "clinician"):
        results = retrieve(cur, embed_model, rerank_model, scanner, QUESTION, role=role)
        groups_seen = {permission_group_of(cur, nct_id) for _, nct_id, _, _ in results}
        entitled = set(allowed_groups(role))
        leaked = groups_seen - entitled

        print(f"role={role}: entitled={sorted(entitled)} saw={sorted(groups_seen)} "
              f"({len(results)} chunks)")

        if leaked:
            failures.append(f"role={role} saw ungranted group(s): {sorted(leaked)}")

    # Separately: confirm the DB actually HAS restricted rows to begin
    # with. If the migration was never run (or the hash split happened to
    # tag zero rows as restricted for this corpus), the test above would
    # pass trivially without proving anything - a restricted chunk that
    # doesn't exist can't leak.
    cur.execute("select count(*) from trial_chunks where permission_group = 'restricted'")
    restricted_count = cur.fetchone()[0]
    print(f"\nrestricted rows in corpus: {restricted_count}")
    if restricted_count == 0:
        failures.append(
            "no restricted rows exist - run db/migrate_permission_groups.py first, "
            "the test above proves nothing without this"
        )

    cur.close()
    conn.close()

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)

    print("\nAll access-control checks passed: researcher never saw a restricted "
          "chunk, clinician was able to.")


if __name__ == "__main__":
    main()
