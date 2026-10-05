"""End-to-end demo + negative proof, run against the live API as an unsafe agent.

    cd cognee-team && .venv/bin/python demo_agent_recall.py          # fast (CHUNKS)
    cd cognee-team && .venv/bin/python demo_agent_recall.py --llm    # LLM answer (GRAPH_COMPLETION)

1. Agent recalls from `public` — the no-ZDR exposure surface, shown working.
2. Agent attempts to read `team` (denied 403 — the boundary).

Default search_type is CHUNKS (no LLM in the loop, deterministic). GRAPH_COMPLETION
produces a real LLM answer from the graph but needs one LLM call per hop — expect
minutes on a small local model (fine on gpt-oss-120b via a hosted preset).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
CREDS = Path(__file__).parent / "credentials"
import tiers
AGENT_EMAIL = tiers.AGENT_EMAILS[-1]
SEARCH_TYPE = "GRAPH_COMPLETION" if "--llm" in sys.argv else "CHUNKS"


def client_for(email: str) -> httpx.Client:
    payload = json.loads((CREDS / f"{email}.json").read_text())
    return httpx.Client(base_url=BASE, headers={"X-Api-Key": payload["api_key"]}, timeout=300)


def main() -> int:
    agent = client_for(AGENT_EMAIL)

    # Names resolve only among datasets the CALLER owns; shared datasets go by id.
    admin = client_for(tiers.ADMIN_EMAIL)
    public_id = next(
        d["id"] for d in admin.get("/api/v1/datasets").json() if d["name"] == "public"
    )

    print(f"== 1. unsafe agent ({AGENT_EMAIL}) recalls from 'public' ({SEARCH_TYPE}) ==")
    r = agent.post(
        "/api/v1/search",
        json={
            "query": "Who can read and write the public tier?",
            "search_type": SEARCH_TYPE,
            "dataset_ids": [public_id],
        },
    )
    if r.status_code != 200:
        print(f"  recall failed: HTTP {r.status_code}: {r.text[:200]}")
        return 1
    data = r.json()
    if isinstance(data, list):
        print(f"  {len(data)} chunk(s) retrieved from public — the agent CAN pull this into its context")
        if data:
            print(f"  sample: {str(data[0])[:200]}")
    else:
        answer = data if isinstance(data, str) else data.get("answer") or str(data)[:300]
        print(f"  LLM answer: {str(answer)[:300]}")

    print("== 2. unsafe agent attempts to read 'team' (admin-owned) ==")
    team_id = next(
        d["id"] for d in admin.get("/api/v1/datasets").json() if d["name"] == "team"
    )
    r = agent.post(
        "/api/v1/search",
        json={"query": "internal team secrets", "search_type": "CHUNKS", "dataset_ids": [team_id]},
    )
    print(f"  GET team content: HTTP {r.status_code} (expect 403)")
    return 0 if r.status_code == 403 else 1


if __name__ == "__main__":
    sys.exit(main())
