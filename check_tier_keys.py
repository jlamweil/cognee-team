#!/usr/bin/env python3
"""Check tier -> principal credential mappings.

Each tier must map to a principal whose <dir>/<email>.json exists, parses as
JSON, and has a non-empty api_key. Prints only a fingerprint (8 chars + …) —
never the full key or password. Exit: 0 ok, 2 missing/invalid, 3 unknown key.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TIER_KEYS = ("P0-public", "P1-contract", "P2-local")


def fingerprint(key: str) -> str:
    return key[:8] + "\u2026"  # …


def check(map_path: Path, credentials_dir: Path) -> int:
    try:
        data = json.loads(map_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read map {map_path}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print("error: map must be a JSON object", file=sys.stderr)
        return 2

    unknown = [k for k in data if k not in TIER_KEYS and k != "_comment"]
    if unknown:
        for key in unknown:
            print(f"unknown tier key: {key}", file=sys.stderr)
        return 3

    ok = True
    for tier in TIER_KEYS:
        email = data.get(tier)
        if not isinstance(email, str) or not email:
            print(f"{tier}: no principal mapped", file=sys.stderr)
            ok = False
            continue
        cred = credentials_dir / f"{email}.json"
        if not cred.is_file():
            print(f"{tier}: credentials file not found ({cred})", file=sys.stderr)
            ok = False
            continue
        try:
            doc = json.loads(cred.read_text())
        except json.JSONDecodeError:
            print(f"{tier}: credentials file is not valid JSON ({cred})", file=sys.stderr)
            ok = False
            continue
        key = doc.get("api_key")
        if not isinstance(key, str) or not key:
            print(f"{tier}: missing or empty api_key ({cred})", file=sys.stderr)
            ok = False
            continue
        print(f"{tier} -> {email} (key {fingerprint(key)})")
    return 0 if ok else 2


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Verify tier -> principal api_key mappings.")
    parser.add_argument("--map", default=None, help="tier-key map JSON (default: tier_keys.local.json when present, else tier_keys.template.json)")
    parser.add_argument("--credentials-dir", default=None, help="credentials dir (default: credentials/)")
    args = parser.parse_args(argv)
    # default map: the host-local real mapping wins when present; the
    # committed template (placeholder-only) is the fallback so a bare
    # run on a fresh clone fails loudly, never silently on stale keys
    local_map = here / "tier_keys.local.json"
    if args.map:
        map_path = Path(args.map)
    elif local_map.is_file():
        map_path = local_map
    else:
        map_path = here / "tier_keys.template.json"
    cred_dir = Path(args.credentials_dir) if args.credentials_dir else here / "credentials"
    return check(map_path, cred_dir)


if __name__ == "__main__":
    sys.exit(main())
