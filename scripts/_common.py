#!/usr/bin/env python3
"""Shared helpers for the MCP diagnostic probes in scripts/.

PII policy: no literal home paths, emails, or dataset names anywhere in
this tree. Credential files are passed as argv paths (opened, never
echoed); dataset names come from argv/env or from a caller-owned dataset
listing at runtime.

The env contract here is the client-mode contract (plan §2.2): the bridge
talks to an EXTERNAL running service, so it is driven by COGNEE_BASE_URL
(no /api/v1 suffix — the client appends API paths itself) with the
x-api-key auth scheme. The serve()-path variable is never set here.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

# Client-mode env contract (plan §2.2).
COGNEE_BASE_URL = "http://127.0.0.1:8000"  # NO /api/v1 suffix
COGNEE_API_AUTH_SCHEME = "x-api-key"       # bare Bearer gets 401

# Pinned bridge package (do not float the version).
COGNEE_MCP_PIN = "cognee-mcp@0.5.7"

# uvx fallback: the absolute per-user install path, expanded at runtime
# (never hardcoded, so no PII enters the source).
DEFAULT_UVX = os.path.join(os.path.expanduser("~"), ".local", "bin", "uvx")


def resolve_uvx():
    """Locate the uvx binary: PATH first, then the absolute fallback."""
    return shutil.which("uvx") or DEFAULT_UVX


def env_contract(api_key, base_env=None):
    """Build the client-mode env for cognee-mcp (plan §2.2).

    Drops the legacy serve()-path variables so a stale inherited env
    cannot shadow the contract.
    """
    env = dict(os.environ if base_env is None else base_env)
    env.pop("COGNEE_SERVICE_URL", None)
    env.pop("TRANSPORT_MODE", None)
    env["COGNEE_BASE_URL"] = COGNEE_BASE_URL
    env["COGNEE_API_AUTH_SCHEME"] = COGNEE_API_AUTH_SCHEME
    env["COGNEE_API_KEY"] = api_key
    return env


def load_cred(cred_path):
    """Read the api_key from a credential JSON. The key is never printed."""
    with open(cred_path) as f:
        return json.load(f)["api_key"]


def list_dataset_names(key, base_url=COGNEE_BASE_URL):
    """Caller-owned dataset names via raw HTTP (by-name probes)."""
    req = urllib.request.Request(base_url + "/api/v1/datasets",
                                 headers={"X-Api-Key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return [d.get("name") for d in json.load(r) if d.get("name")]


# --- stdio JSON-RPC plumbing (shared by the bridge probes) --------------

def spawn_bridge(env):
    """Spawn the pinned cognee-mcp bridge over stdio."""
    return subprocess.Popen(
        [resolve_uvx(), COGNEE_MCP_PIN],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, text=True, bufsize=1)


def rpc_send(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def rpc_recv(proc, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                err = proc.stderr.read()[-3000:]
                raise SystemExit(f"SERVER_EXITED rc={proc.returncode}\nSTDERR:\n{err}")
            time.sleep(0.05)
            continue
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except Exception:
            sys.stderr.write(f"NONJSON: {line[:300]}\n")
    raise SystemExit(f"TIMEOUT waiting for JSON-RPC response (>{timeout}s)")


def rpc_call(proc, name, args, rid, timeout=180):
    """Call a bridge tool; returns (text, isError)."""
    rpc_send(proc, {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                    "params": {"name": name, "arguments": args}})
    r = rpc_recv(proc, timeout)
    res = r.get("result", {})
    if isinstance(res, dict):
        text = "".join(c.get("text", "") for c in res.get("content", [])
                       if isinstance(c, dict))
        return text, res.get("isError")
    return str(r), None


def handshake(proc):
    """MCP initialize + notifications/initialized. Returns the init reply."""
    rpc_send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "probe", "version": "0.0.1"}}})
    init = rpc_recv(proc)
    if "error" in init:
        raise SystemExit(f"INIT ERROR: {init['error']}")
    rpc_send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    time.sleep(1)
    return init


def shutdown(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
