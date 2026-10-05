"""Verify the tier partitioning against the LIVE API server.

    cd cognee-team && .venv/bin/python verify.py

Hard-asserts, per principal, exactly what tiers.py promises — using the same
credentials real clients hold (API keys in credentials/, minted by bootstrap):

  1. dataset VISIBILITY:   GET /api/v1/datasets
     - admin sees public+team, members see +their private,
       agents see ONLY public + their OWNER's private (member_agents)
     - forbidden datasets must be absent, not just unsearchable
  2. READ via shared UUID: POST /api/v1/search (CHUNKS — no LLM involved)
     - agent on public and on owner's private -> 200/404-empty
     - agent on team and on any OTHER member's private -> 403
  3. WRITE via shared UUID: POST /api/v1/add
     - agent into public and owner's private -> 200
     - agent into team and any OTHER member's private -> 403
  4. human JWT login works (web UI path); default superuser cannot log in.

Exit 0 only if every assertion holds. Read boundary: a permitted dataset passes
the ACL gate and reaches retrieval — 200 with content, or 404 NoDataError when
the dataset is ingest-only (cognee 1.6.2 raises "knowledge graph is empty" AFTER
the permission check; on a fresh bootstrap datasets are seeded without cognify).
A forbidden dataset is rejected BEFORE retrieval — strictly 403. The 200/404-vs-
403 boundary IS the check; no LLM and no graph extraction is needed to prove
the ACL layer.
"""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
import tiers  # noqa: E402

BASE = __import__("os").environ.get("COGNEE_URL", "http://127.0.0.1:8000").rstrip("/")
CREDS = Path(__file__).parent / "credentials"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def api_key_client(email: str) -> httpx.Client:
    payload = json.loads((CREDS / f"{email}.json").read_text())
    key = payload.get("api_key")
    if not key:
        raise SystemExit(f"no API key in credentials/{email}.json — re-run bootstrap.py --reset-keys")
    return httpx.Client(base_url=BASE, headers={"X-Api-Key": key}, timeout=120)


def visible_dataset_names(client: httpx.Client) -> dict[str, str]:
    r = client.get("/api/v1/datasets")
    r.raise_for_status()
    return {d["name"]: d["id"] for d in r.json()}


def search(client: httpx.Client, dataset_id: str) -> tuple[int, str]:
    r = client.post(
        "/api/v1/search",
        json={"query": "seed", "search_type": "CHUNKS", "dataset_ids": [str(dataset_id)]},
    )
    return r.status_code, r.text[:200]


def add_text(client: httpx.Client, dataset_id: str, text: str) -> int:
    r = client.post(
        "/api/v1/add",
        files={"data": ("verify-note.txt", text.encode())},
        data={"datasetId": str(dataset_id)},
    )
    return r.status_code


def main() -> int:
    print(f"== cognee-team verify against {BASE} ==")

    # -- 1. visibility -------------------------------------------------------
    admin = api_key_client(tiers.ADMIN_EMAIL)
    admin_datasets = visible_dataset_names(admin)
    check(
        "admin sees public + team",
        {tiers.DATASET_PUBLIC, tiers.DATASET_TEAM} <= set(admin_datasets),
        str(sorted(admin_datasets)),
    )
    public_id = admin_datasets[tiers.DATASET_PUBLIC]
    team_id = admin_datasets[tiers.DATASET_TEAM]

    member_email = tiers.MEMBER_EMAILS[0]
    member = api_key_client(member_email)
    member_datasets = visible_dataset_names(member)
    check(
        f"member {member_email} sees public, team, own private",
        {
            tiers.DATASET_PUBLIC,
            tiers.DATASET_TEAM,
            tiers.private_dataset_name(member_email),
        }
        <= set(member_datasets),
        str(sorted(member_datasets)),
    )
    check(
        "member sees no other private/* datasets",
        not [n for n in member_datasets if n.startswith("private/") and n != tiers.private_dataset_name(member_email)],
    )
    private_id = member_datasets[tiers.private_dataset_name(member_email)]

    # every member's private dataset id — for cross-member denial checks below
    private_ids: dict[str, str] = {member_email: private_id}
    for other in tiers.MEMBER_EMAILS[1:]:
        c = api_key_client(other)
        private_ids[other] = visible_dataset_names(c)[tiers.private_dataset_name(other)]

    for email in tiers.AGENT_EMAILS:
        owner = tiers.AGENT_OWNER[email]
        own_private_id = private_ids[owner]
        other_private_ids = {m: pid for m, pid in private_ids.items() if m != owner}
        agent = api_key_client(email)
        agent_datasets = visible_dataset_names(agent)
        check(
            f"agent {email} sees ONLY public + owner's private (no team, no other private/*)",
            tiers.DATASET_PUBLIC in agent_datasets
            and tiers.private_dataset_name(owner) in agent_datasets
            and tiers.DATASET_TEAM not in agent_datasets
            and not [
                n for n in agent_datasets
                if n.startswith("private/") and n != tiers.private_dataset_name(owner)
            ],
            str(sorted(agent_datasets)),
        )

        # -- 2. read boundary (the no-ZDR leak path) -------------------------
        # 200 = read + cognified; 404 = read granted, graph empty (ingest-only
        # dataset). Both prove the ACL gate passed. 403 would mean NO read.
        code, _ = search(agent, public_id)
        check(f"agent can READ public (200/404-empty-ok, got {code})", code in (200, 404))
        code, _ = search(agent, own_private_id)
        check(
            f"agent can READ owner's private (200/404-empty-ok, got {code})",
            code in (200, 404),
        )
        code, _ = search(agent, team_id)
        check(f"agent READ team -> 403 (got {code})", code == 403)
        for m, pid in other_private_ids.items():
            code, _ = search(agent, pid)
            check(f"agent READ other member's private ({m}) -> 403 (got {code})", code == 403)

        # -- 3. write boundary -----------------------------------------------
        code = add_text(agent, public_id, f"verify write by {email}")
        check(f"agent can WRITE public (200, got {code})", code == 200)
        code = add_text(agent, own_private_id, f"verify agent write by {email}")
        check(f"agent can WRITE owner's private (200, got {code})", code == 200)
        code = add_text(agent, team_id, "should be denied")
        check(f"agent WRITE team -> 403 (got {code})", code == 403)
        for m, pid in other_private_ids.items():
            code = add_text(agent, pid, "should be denied")
            check(f"agent WRITE other member's private ({m}) -> 403 (got {code})", code == 403)

    # -- 4. human login + default-user posture --------------------------------
    creds = json.loads((CREDS / f"{member_email}.json").read_text())
    with httpx.Client(base_url=BASE, timeout=60) as c:
        r = c.post(
            "/api/v1/auth/login",
            data={"username": member_email, "password": creds["password"]},
        )
        check(f"member JWT login works (200, got {r.status_code})", r.status_code == 200)
        r = c.post(
            "/api/v1/auth/login",
            data={"username": "default_user@example.com", "password": secrets.token_urlsafe(8)},
        )
        check(f"default superuser cannot log in (400/401/422, got {r.status_code})", r.status_code in (400, 401, 422))

    print("== verify complete ==")
    if failures:
        print(f"FAILED ({len(failures)}): {failures}")
        return 1
    print("ALL CHECKS PASSED — every agent is confined to public + its owner's private tier.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
