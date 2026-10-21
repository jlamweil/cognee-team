#!/usr/bin/env python3
"""Read-only dump of each principal's EFFECTIVE read/write dataset footprint.

Resolves permissions the way cognee does at request time (direct grants +
role inheritance + tenant membership), so the output is the true
"can this principal do it" set -- the thing you snapshot before and after an
ACL reconciliation and diff.

    cd cognee-team
    .venv/bin/python scripts/dump_acl.py                     # human-readable matrix
    .venv/bin/python scripts/dump_acl.py --json acl.before.json
    .venv/bin/python scripts/dump_acl.py --diff acl.before.json   # added/removed

Read-only: issues SELECTs against the ACL database; grants and revokes
nothing. Safe to run while the API server is up (live read/write *probes* are
verify.py's job; this is the effective-set ground truth).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tiers  # noqa: E402

from cognee.modules.users.methods import get_user_by_email  # noqa: E402
from cognee.modules.users.permissions.methods import (  # noqa: E402
    get_all_user_permission_datasets,
)


def _principals() -> list[tuple[str, str]]:
    out = [("admin", tiers.ADMIN_EMAIL)]
    out += [("member", e) for e in tiers.MEMBER_EMAILS]
    out += [("unsafe-agent", e) for e in tiers.AGENT_EMAILS]
    out += [("safe-agent", e) for e in tiers.SAFE_AGENT_EMAILS]
    return out


async def _effective(user) -> dict:
    reads = await get_all_user_permission_datasets(user, tiers.READ)
    writes = await get_all_user_permission_datasets(user, tiers.WRITE)
    return {
        "read": sorted(d.name for d in reads),
        "write": sorted(d.name for d in writes),
    }


async def _snapshot() -> dict[str, dict]:
    snap: dict[str, dict] = {}
    for kind, email in _principals():
        key = f"{kind}:{email}"
        user = await get_user_by_email(email)
        if user is None:
            snap[key] = {"read": [], "write": [], "error": "user not found"}
        else:
            snap[key] = await _effective(user)
    return snap


def _diff(before: dict[str, dict], after: dict[str, dict]) -> None:
    any_change = False
    for key in sorted(set(before) | set(after)):
        b = before.get(key, {"read": [], "write": []})
        a = after.get(key, {"read": [], "write": []})
        for perm in ("read", "write"):
            added = sorted(set(a.get(perm, [])) - set(b.get(perm, [])))
            removed = sorted(set(b.get(perm, [])) - set(a.get(perm, [])))
            if added or removed:
                any_change = True
                print(f"{key} {perm}:")
                if added:
                    print(f"    + {', '.join(added)}")
                if removed:
                    print(f"    - {', '.join(removed)}")
    if not any_change:
        print("(no change vs snapshot)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", metavar="PATH", help="write a machine-readable snapshot to PATH")
    ap.add_argument("--diff", metavar="BEFORE_JSON", help="compare this run against a prior snapshot")
    args = ap.parse_args()

    snap = asyncio.run(_snapshot())

    if args.json:
        Path(args.json).write_text(json.dumps(snap, indent=2) + "\n")
        print(f"snapshot written -> {args.json}")

    if args.diff:
        before = json.loads(Path(args.diff).read_text())
        _diff(before, snap)
    else:
        for key, sets in snap.items():
            err = f"  ({sets['error']})" if "error" in sets else ""
            print(f"{key}:")
            print(f"    read : {', '.join(sets['read']) or 'empty'}")
            print(f"    write: {', '.join(sets['write']) or 'empty'}{err}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
