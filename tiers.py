"""Team partitioning model — the single source of truth for tiers and ACLs.

Everything bootstrap.py grants, and everything verify.py asserts, is defined
here. Change the matrix here, re-run bootstrap (idempotent), re-run verify.

Model
-----
One tenant (``team``) holds every principal: humans AND unsafe AI agent
providers. Tiers are datasets, not tenants:

===============  =========================  ======================================
tier             datasets                   who has access
===============  =========================  ======================================
public           ``public``                 members rw, agent-providers rw
team             ``team``                   members rw only (no agents)
private/<name>   ``private/<member>``       owner (full) + the owner's OWN agents
                                           (rw); nobody else — incl. admin
===============  =========================  ==================================

Per-member agent providers (own AI, own projects)
-------------------------------------------------
A member's agent providers (``member_agents`` in roster.json) are partitioned
with their owner: each gets ``public`` via the ``agent-provider`` role PLUS a
DIRECT read/write grant on ``private/<owner>`` and NOTHING else. So a person's
own AI can work their private projects, while no other member, no other
member's agent, and not even the admin can read that tier. Agents of member M
are created with ``parent_user_id = M`` so anything an agent ingests (scratch
datasets it owns) is inherited downward by M only.

Why unsafe agent providers cannot touch ``team``/``private`` even with tenant
membership: cognee only ever unions *explicit* ACL grants (direct + role +
tenant) and tenants start with ZERO permissions. Membership alone grants
nothing, so an agent principal holds exactly the grants below — read/write on
``public`` — and a recall scoped to its permitted datasets never sees the
others. A dataset a no-ZDR provider can pull into its context is, by
construction, public-tier only.

OPERATOR RULE — never grant anything to the TENANT principal. A tenant-level
grant is inherited by every member INCLUDING the unsafe agent users. Grant to
the ``member`` role (humans) instead. bootstrap.py and this docstring are the
only places tenant grants would ever be written.

No-ZDR providers and writes: an agent that "remembers" with a dataset *name*
resolves names only against datasets IT owns (cognee rule), so it can only
pollute its own scratch datasets. Writing into the shared ``public`` dataset
requires its UUID and the ``write`` grant — kept on by team decision, revoke
with one line (see README "Revoke a provider's write access").
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------

TENANT_NAME = "team"

# Identities live in roster.json (gitignored, chmod 600) -- NOT in this file,
# so the code can be shared without leaking who is on the team. Copy
# roster.template.json to roster.json and edit that. Re-run bootstrap after
# any change (idempotent).
import json as _json
import os as _os

_roster_path = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "roster.json"
)
with open(_roster_path) as _f:
    _roster = _json.load(_f)

DOMAIN = _roster["domain"]
ADMIN_EMAIL = _roster["admin_email"]
MEMBER_EMAILS = list(_roster["member_emails"])

# member -> that member's own agent providers (unsafe, no-ZDR). Every agent is
# partitioned with its owner: public + the OWNER's private tier, nothing else.
MEMBER_AGENTS: dict[str, list[str]] = {
    m: list(a) for m, a in _roster.get("member_agents", {}).items()
}

# Derived flat views (do not edit here — edit roster.json).
AGENT_OWNER: dict[str, str] = {
    agent: member for member, agents in MEMBER_AGENTS.items() for agent in agents
}
AGENT_EMAILS = list(AGENT_OWNER)

MEMBER_ROLE = "member"            # humans: public + team
AGENT_ROLE = "agent-provider"     # unsafe providers: public (+ owner's private)

# Cognee permission names (the only four valid values).
READ, WRITE, DELETE, SHARE = "read", "write", "delete", "share"

DATASET_PUBLIC = "public"
DATASET_TEAM = "team"


def private_dataset_name(member_email: str) -> str:
    """Tier-3 dataset for one member, e.g. ``private/alice@example_com``.

    Cognee rejects dataset names containing dots or spaces on the add path
    (ValueError -> HTTP 500) even though creation and id-addressed reads
    succeed — so emails are sanitized (dots -> underscores). Unique in
    practice; the email itself remains the identity everywhere else.
    """
    return "private/" + member_email.replace(".", "_")


# ---------------------------------------------------------------------------
# The matrix — (role or owner) -> dataset -> permissions
# ---------------------------------------------------------------------------

# Grants on shared datasets, by ROLE (never by tenant, never per user).
ROLE_MATRIX: dict[str, dict[str, list[str]]] = {
    MEMBER_ROLE: {
        DATASET_PUBLIC: [READ, WRITE],
        DATASET_TEAM: [READ, WRITE],
    },
    AGENT_ROLE: {
        DATASET_PUBLIC: [READ, WRITE],  # team decision: rw on public tier
        # DATASET_TEAM deliberately absent — unsafe providers never see it.
    },
}

# Owner-only tier: create_authorized_dataset grants the creator
# read+write+delete+share automatically; nobody else gets anything.
# Admin intentionally has NO access to members' private datasets
# (superuser does not bypass dataset permissions in cognee).


def visible_datasets_for(email: str) -> set[str]:
    """Datasets a freshly-bootstrapped principal must see (verify.py)."""
    if email == ADMIN_EMAIL:
        # Admin owns public+team; members' private datasets stay owner-only.
        return {DATASET_PUBLIC, DATASET_TEAM}
    if email in MEMBER_EMAILS:
        return {DATASET_PUBLIC, DATASET_TEAM, private_dataset_name(email)}
    if email in AGENT_OWNER:
        # public via role + owner's private via direct grant. A member-scoped
        # agent never sees team or any other member's private tier.
        return {DATASET_PUBLIC, private_dataset_name(AGENT_OWNER[email])}
    raise ValueError(f"unknown principal: {email}")
