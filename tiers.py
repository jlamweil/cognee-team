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
public           ``public``                 members rw, agent-providers rw,
                                             safe-providers RO (agents never
                                             write public)
team             ``team``                   members rw + safe-providers rw
                                           (no unsafe agents)
private/<name>   ``private/<member>``       owner (full) + the owner's OWN agents
                                           and safe-providers (rw); nobody else
                                           — incl. admin
private-safe/<n> ``private-safe/<member>``  owner (full) + the owner's OWN
                                           safe-providers (rw) ONLY — no unsafe
                                           agents, no other member, no admin
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

Per-member safe (ZDR) providers
-------------------------------
A member's safe providers (``member_safe_agents`` in roster.json) are providers
with a zero-data-retention guarantee. They get EXACTLY what an unsafe provider
gets — ``public`` via the ``safe-provider`` role PLUS a DIRECT read/write grant
on ``private/<owner>`` — PLUS read+write on the ``team`` tier PLUS a DIRECT
read/write grant on the owner's safe-only ``private-safe/<owner>`` tier
(sensitive projects, ZDR models only). Everything else is identical to the
agent path: partitioned with the owner, same ``parent_user_id``, same per-owner
direct grants, same owner's private tier. The differences from the unsafe path
are the added ``team`` read+write and the owner's ``private-safe`` tier.

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
pollute its own scratch datasets. Agents are read-only on the shared
``public`` tier -- they can recall from it but never write it -- so content
read from a private tier cannot be composed back into public. Only human
members write public (see README "Revoke a provider's write access").
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

# member -> that member's own safe (ZDR) providers. Same partitioning as the
# unsafe path, plus read+write on the ``team`` tier (role ``safe-provider``).
MEMBER_SAFE_AGENTS: dict[str, list[str]] = {
    m: list(a) for m, a in _roster.get("member_safe_agents", {}).items()
}
SAFE_AGENT_OWNER: dict[str, str] = {
    agent: member for member, agents in MEMBER_SAFE_AGENTS.items() for agent in agents
}
SAFE_AGENT_EMAILS = list(SAFE_AGENT_OWNER)

MEMBER_ROLE = "member"            # humans: public + team
AGENT_ROLE = "agent-provider"     # unsafe providers: public (+ owner's private)
SAFE_AGENT_ROLE = "safe-provider"     # safe (ZDR) providers: public + team (+ owner's private)

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


def private_safe_dataset_name(member_email: str) -> str:
    """Safe-only tier-3 dataset, e.g. private-safe/alice@example_com (sanitized)."""
    return "private-safe/" + member_email.replace(".", "_")


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
        DATASET_PUBLIC: [READ],  # read-only on public: agents pull from public, never write it
        # DATASET_TEAM deliberately absent — unsafe providers never see it.
    },
    SAFE_AGENT_ROLE: {
        DATASET_PUBLIC: [READ],  # read-only on public: safe providers may not write public
        DATASET_TEAM: [READ, WRITE],   # safe (ZDR) providers may read+write the team tier
    },
}

# Owner-only tier: create_authorized_dataset grants the creator
# read+write+delete+share automatically; nobody else gets anything.
# Admin intentionally has NO access to members' private datasets
# (superuser does not bypass dataset permissions in cognee).


def visible_datasets_for(email: str) -> set[str]:
    """Datasets a freshly-bootstrapped principal must see (verify.py)."""
    if email in MEMBER_EMAILS:
        return {DATASET_PUBLIC, DATASET_TEAM, private_dataset_name(email), private_safe_dataset_name(email)}
    if email == ADMIN_EMAIL:
        return {DATASET_PUBLIC, DATASET_TEAM}
    if email in AGENT_OWNER:
        # unsafe: public + owner's private only (NO team, NO private-safe)
        return {DATASET_PUBLIC, private_dataset_name(AGENT_OWNER[email])}
    if email in SAFE_AGENT_OWNER:
        o = SAFE_AGENT_OWNER[email]
        return {DATASET_PUBLIC, DATASET_TEAM, private_dataset_name(o), private_safe_dataset_name(o)}
    raise ValueError(f"unknown principal: {email}")
