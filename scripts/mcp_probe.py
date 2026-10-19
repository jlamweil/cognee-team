#!/usr/bin/env python3
"""Stage-1 MCP stdio probe: spawn cognee-mcp, initialize, list tools.

Usage: mcp_probe.py <path-to-credential.json>   (key read silently, never printed)

Read-only: only initialize + tools/list; no tools/call. The bridge is
launched pinned (cognee-mcp@0.5.7) with the client-mode env contract
(COGNEE_BASE_URL without /api/v1, x-api-key scheme) — see README.md here.
"""
import json
import sys

import _common


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: mcp_probe.py <path-to-credential.json>")
    key = _common.load_cred(argv[1])
    proc = _common.spawn_bridge(_common.env_contract(key))
    try:
        init = _common.handshake(proc)
        print("INIT result:", json.dumps(init.get("result", {}), indent=1)[:1200])
        _common.rpc_send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                                "params": {}})
        tools = _common.rpc_recv(proc, 60)
        if "error" in tools:
            raise SystemExit(f"TOOLS ERROR: {tools['error']}")
        tl = tools["result"]["tools"]
        print(f"TOOL_COUNT: {len(tl)}")
        for t in tl:
            desc = (t.get("description") or "").replace("\n", " ")[:120]
            print(f"- {t['name']}: {desc}")
    finally:
        _common.shutdown(proc)


if __name__ == "__main__":
    main(sys.argv)
