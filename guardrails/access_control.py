"""Synthetic access-control layer for Phase 4 Step 3.

The corpus is entirely public ClinicalTrials.gov data - nothing here is
actually sensitive. This module exists to build and demonstrate the real
*pattern* used to gate a genuinely sensitive corpus (e.g. one containing
PHI): a caller identity maps to a fixed set of entitlements, and anything
outside those entitlements should be unreachable, not just hidden. The
enforcement itself (retrieval/hybrid_search.py filtering rows in SQL, not
in Python after the fact) is real and would work identically against real
entitlement data; only the roles and the trial_chunks.permission_group
tagging (db/migrate_permission_groups.py) are made up for this demo.

Two permission groups exist on trial_chunks: "public" and "restricted".
Two synthetic roles are defined below, entitled to different subsets.
"""

# Deliberately a plain dict, not a database table: for a real system this
# would live in an identity/entitlements service, but for a demo of the
# retrieval-side enforcement mechanism, a hardcoded map is the simplest
# thing that's still honest about the pattern - "given a caller identity,
# look up what they're allowed to see."
ROLE_ENTITLEMENTS = {
    "researcher": ["public"],
    "clinician": ["public", "restricted"],
}


def allowed_groups(role):
    """Return the list of permission_group values `role` is entitled to
    query. Raises on an unrecognized role rather than defaulting to
    "public" or to an empty list - an access-control check that fails
    open (silently allowing or silently returning nothing) on bad input
    is a real class of security bug; failing loudly with an error is the
    correct behavior for an unknown caller identity."""
    if role not in ROLE_ENTITLEMENTS:
        raise ValueError(
            f"Unknown role: {role!r} (known roles: {sorted(ROLE_ENTITLEMENTS)})"
        )
    return ROLE_ENTITLEMENTS[role]


def check_access(role, permission_group):
    """Is `role` entitled to see a document tagged `permission_group`?
    Exposed as its own MCP tool (mcp_server/server.py) so a caller can ask
    this directly about a specific document, independent of running a
    full retrieval query - the same entitlement check retrieve() applies
    internally to every row, just callable on its own."""
    return permission_group in allowed_groups(role)


if __name__ == "__main__":
    # Self-test: no database or model loading needed, this module is pure
    # logic - run directly to sanity-check the entitlement table itself.
    assert allowed_groups("researcher") == ["public"]
    assert allowed_groups("clinician") == ["public", "restricted"]
    assert check_access("researcher", "public") is True
    assert check_access("researcher", "restricted") is False
    assert check_access("clinician", "restricted") is True

    try:
        allowed_groups("intern")
        raise AssertionError("expected ValueError for an unknown role")
    except ValueError:
        pass

    print("All access_control self-tests passed.")
