#!/usr/bin/env python3
"""MCP recall BY NAME through the bridge (all the client can send is names)
plus the bare-recall fallback.

Usage: mcp_names.py <path-to-credential.json> [dataset-name ...]

With no dataset args, the probe lists the caller's OWN datasets via raw
HTTP and recalls each by name. Recall by name on a SHARED tier is expected
to fail with DatasetNotFoundError 404 (names-only client vs caller-owned
resolution) — use raw HTTP dataset_ids for shared tiers. See README.md.
"""
import sys

import _common


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: mcp_names.py <path-to-credential.json> [dataset-name ...]")
    key = _common.load_cred(argv[1])
    names = argv[2:] or _common.list_dataset_names(key)
    if not names:
        raise SystemExit("no dataset names to probe (pass names, or the caller owns none)")
    proc = _common.spawn_bridge(_common.env_contract(key))
    try:
        _common.handshake(proc)
        for i, name in enumerate(names, start=20):
            out, _ = _common.rpc_call(proc, "recall",
                                      {"query": "probe", "datasets": name,
                                       "search_type": "CHUNKS"}, i)
            print(f"MCP name={name}:", out.replace("\n", " ")[:150])
        out, _ = _common.rpc_call(proc, "recall", {"query": "probe",
                                                   "search_type": "CHUNKS"},
                                  20 + len(names))  # bare: client falls back to listing names
        print("MCP bare recall:", out.replace("\n", " ")[:200])
    finally:
        _common.shutdown(proc)


if __name__ == "__main__":
    main(sys.argv)
