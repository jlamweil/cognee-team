#!/usr/bin/env python3
"""Raw-HTTP tier probe via POST /api/v1/recall with dataset_ids (UUIDs).

Usage: curl_tier2.py <agent-cred.json> <admin-cred.json> [dataset-name ...]

Dataset UUIDs are resolved through the ADMIN dataset listing — names are
never hardcoded in this source. With no name args the probe uses the
standard tier names present in the listing (public, team) plus every
private/* dataset found there.
"""
import json
import sys
import urllib.error
import urllib.request

import _common

BASE = _common.COGNEE_BASE_URL


def _get(path, key):
    req = urllib.request.Request(BASE + path, headers={"X-Api-Key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode()


def _post(path, key, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"X-Api-Key": key,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read().decode()[:250]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:250]


def _blocked(out):
    return "403" in out or "forbidden" in out.lower() or "permission" in out.lower()


def main(argv):
    if len(argv) < 3:
        raise SystemExit(
            "usage: curl_tier2.py <agent-cred.json> <admin-cred.json> [dataset-name ...]")
    agent = _common.load_cred(argv[1])
    admin = _common.load_cred(argv[2])
    _, a_raw = _get("/api/v1/datasets", admin)
    ids = {d["name"]: d["id"] for d in json.loads(a_raw) if d.get("name")}
    names = argv[3:]
    if not names:
        names = [n for n in ("public", "team") if n in ids]
        names += sorted(n for n in ids if n.startswith("private/"))
    missing = [n for n in names if n not in ids]
    if missing:
        raise SystemExit(f"dataset(s) not in admin listing: {', '.join(missing)}")
    tests = [(f"AGENT {n}", agent, ids[n]) for n in names]
    if "public" in ids:
        tests.append(("ADMIN public", admin, ids["public"]))
    for label, key, ds in tests:
        body = {"query": "probe", "top_k": 3, "search_type": "CHUNKS",
                "system_prompt": "noop", "dataset_ids": [ds]}
        code, out = _post("/api/v1/recall", key, body)
        print(f"{label:18s} http={code} blocked={_blocked(out)} :: "
              f"{out.replace(chr(10), ' ')[:130]}")


if __name__ == "__main__":
    main(sys.argv)
