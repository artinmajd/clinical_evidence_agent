"""One-time migration: tags the trial_chunks rows already sitting in the
database with a synthetic permission_group, since db/schema.sql's new
column only decides a value ('public') for brand-new rows going forward -
it has no way to retroactively decide anything for the 415 rows that were
already there before this column existed.

Deliberately deterministic, not random. Every run of this script against
the same data produces the exact same public/restricted split - which
matters here specifically because the whole point of this step is to
demo access control consistently (run the demo twice, get the same
"clinician can see it, researcher can't" result both times), not to prove
some idea works on a special one-off dice roll.

The trick: hash each trial's NCT ID - a stable identifier that never
changes for a given trial - into a number, then bucket by that number
modulo 5, so roughly 1 in 5 trials (~20%) lands in "restricted." This
runs as a single UPDATE inside Postgres itself rather than looping over
every row in Python:

    abs(('x' || substr(md5(nct_id), 1, 8))::bit(32)::int) % 5 = 0

Read inside out: md5(nct_id) is a 32-character hex string, always
identical for the same nct_id. substr(..., 1, 8) keeps the first 8 hex
characters (32 bits' worth). Prefixing with 'x' and casting to bit(32)
tells Postgres to read those characters as hexadecimal rather than as
literal 0/1 binary digits. Casting that bit(32) to int reinterprets the
same 32 bits as a plain signed integer. abs(...) % 5 then buckets that
integer into 5 roughly-equal-sized groups (0-4); landing in group 0 (~20%
of trials, by definition of "1 in 5") means "restricted," anything else
means "public." No randomness anywhere in this - the same nct_id always
hashes to the same bucket, forever.
"""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Keep CONNECTION local so this script can be run as
# `python db/migrate_permission_groups.py` without requiring the project
# root to be on sys.path (importing retrieval.hybrid_search fails in that
# mode, and would also pull in heavy embedding deps for a SQL migration).
CONNECTION = {
    "host": os.environ["SUPABASE_DB_HOST"],
    "port": os.environ.get("SUPABASE_DB_PORT", "5432"),
    "dbname": os.environ.get("SUPABASE_DB_NAME", "postgres"),
    "user": os.environ.get("SUPABASE_DB_USER", "postgres"),
    "password": os.environ["SUPABASE_DB_PASSWORD"],
}


def main():
    conn = psycopg2.connect(**CONNECTION)
    cur = conn.cursor()

    cur.execute(
        """
        update trial_chunks
        set permission_group = case
            when abs(
                ('x' || substr(md5(nct_id), 1, 8))::bit(32)::int
            ) % 5 = 0
            then 'restricted'
            else 'public'
        end
        """
    )
    updated = cur.rowcount
    conn.commit()

    cur.execute(
        """
        select permission_group, count(*)
        from trial_chunks
        group by permission_group
        order by permission_group
        """
    )
    print(f"Updated {updated} rows.")
    for group, count in cur.fetchall():
        print(f"  {group}: {count}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
