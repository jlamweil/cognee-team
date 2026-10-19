#!/usr/bin/env python3
"""Per-agent memory loop via the MCP bridge: remember -> list datasets ->
recall by name -> forget (cleanup). Keys never printed.

Usage: mcp_agentmem.py <path-to-credential.json>

The agent OWNS its auto-scoped dataset, so by-name recall works through the
bridge (unlike shared tiers — see README.md). The probe note is overridable
via the COGNEE_PROBE_NOTE env var.
"""
import os
import sys
import time

import _common


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: mcp_agentmem.py <path-to-credential.json>")
    key = _common.load_cred(argv[1])
    note = os.environ.get("COGNEE_PROBE_NOTE", "mcp-agentmem probe note")
    before = _common.list_dataset_names(key)
    proc = _common.spawn_bridge(_common.env_contract(key))
    try:
        _common.handshake(proc)
        rem, remerr = _common.rpc_call(proc, "remember", {"data": note}, 30, timeout=240)
        print("REMEMBER:", rem.replace("\n", " ")[:250], "| isError=", remerr)
        time.sleep(8)  # allow cognify/ingest to register the dataset + item
        after = _common.list_dataset_names(key)
        new = [n for n in after if n not in before]
        print("NEW DATASET(S) SEEN BY AGENT:", new)
        if new:
            target = new[0]
            rec, recerr = _common.rpc_call(proc, "recall",
                                           {"query": note, "datasets": target,
                                            "search_type": "CHUNKS"}, 31)
            print(f"RECALL by name={target!r}:", rec.replace("\n", " ")[:250],
                  "| isError=", recerr, "| NOTE_FOUND=", note in rec)
            fg, _ = _common.rpc_call(proc, "forget", {"dataset": target}, 32)
            print("FORGET cleanup:", fg.replace("\n", " ")[:150])
    finally:
        _common.shutdown(proc)


if __name__ == "__main__":
    main(sys.argv)
