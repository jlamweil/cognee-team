"""One-time: cognify the seeded public dataset so recall returns real content.

    cd cognee-team && .venv/bin/python cognify_seed.py

Uses the configured LLM (default: local Ollama qwen2.5:7b-instruct + fastembed
embeddings) via the live API as admin — doubles as the end-to-end check of the
extraction path. Only needed once per tier dataset that should be searchable;
remember() cognifies automatically afterwards.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

import tiers

BASE = "http://127.0.0.1:8000"
CREDS = Path(__file__).parent / "credentials"
DATASETS = sys.argv[1:] or ["public"]

# NOTE: the default (strict) KnowledgeGraph schema + json_mode + qwen2.5:7b is
# the combination that validates end-to-end on local Ollama; do not add a lenient
# graph_model override — it lets empty ids through and crashes UUID conversion.


def admin_client() -> httpx.Client:
    payload = json.loads((CREDS / f"{tiers.ADMIN_EMAIL}.json").read_text())
    return httpx.Client(
        base_url=BASE,
        headers={"X-Api-Key": payload["api_key"]},
        timeout=900,
    )


def main() -> int:
    datasets = {d["name"]: d["id"] for d in admin_client().get("/api/v1/datasets").json()}
    ok = True
    for name in DATASETS:
        if name not in datasets:
            print(f"dataset '{name}' not found — re-run bootstrap.py")
            ok = False
            continue
        print(f"cognifying '{name}' (LLM extraction — may take a while on CPU)...")
        r = admin_client().post(
            "/api/v1/cognify",
            json={"dataset_ids": [str(datasets[name])]},
        )
        print(f"  cognify '{name}': HTTP {r.status_code}")
        if r.status_code not in (200, 202):
            print(f"  body: {r.text[:300]}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
