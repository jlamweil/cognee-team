"""Offline tests for the parameterized MCP diagnostic probes (scripts/).

No live service required. The tests assert, by importing the scripts'
builder functions:

1. env contract builder: COGNEE_BASE_URL == "http://127.0.0.1:8000"
   (no /api/v1 suffix), COGNEE_API_AUTH_SCHEME == "x-api-key", a
   COGNEE_API_KEY, and NEITHER COGNEE_SERVICE_URL nor any COGNEE_* base
   URL ending in /api/v1.
2. uvx resolver: uses shutil.which("uvx") when present on PATH; falls
   back to the absolute per-user install path (<HOME>/.local/bin/uvx,
   expanded at runtime so no PII literal enters this file) when not.
3. credential paths and dataset names come only from argv/env: probe
   sources contain no literal home paths, no email-like dataset names,
   and no PII (the repo's public-release scrub pattern).

Run: .venv/bin/python -m pytest tests/ -q
"""
import json
import os
import re
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import _common  # noqa: E402
import mcp_probe  # noqa: E402
import mcp_names  # noqa: E402
import mcp_agentmem  # noqa: E402
import curl_tier2  # noqa: E402

PROBE_SCRIPTS = ("mcp_probe.py", "mcp_names.py", "mcp_agentmem.py", "curl_tier2.py")
ALL_SOURCES = PROBE_SCRIPTS + ("_common.py",)
# the repo's public-release PII scrub pattern (see git history: "scrub
# personal paths and PII for public release"). The fragments are split so
# this test file itself passes the very same scrub grep.
PII_PATTERNS = ("j" + "lam", "/h" + "ome/", "~/" + "1/", "un" + "istra")
PII_RE = re.compile("|".join(PII_PATTERNS))
# email-like dataset names (private/<name>@<domain>); the uvx version pin
# below is NOT a dataset name and is stripped before this check
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")
UVX_PIN = "cognee-mcp@0.5.7"


def read(name):
    return (SCRIPTS_DIR / name).read_text()


# --- 1. env contract ---------------------------------------------------

def test_env_contract_is_client_mode():
    env = _common.env_contract("test-agent-key", base_env={})
    assert env["COGNEE_BASE_URL"] == "http://127.0.0.1:8000"
    assert env["COGNEE_API_AUTH_SCHEME"] == "x-api-key"
    assert env["COGNEE_API_KEY"] == "test-agent-key"


def test_env_contract_has_no_service_url_or_api_v1_base():
    env = _common.env_contract("test-agent-key", base_env={})
    assert "COGNEE_SERVICE_URL" not in env
    for key, value in env.items():
        if key.startswith("COGNEE_"):
            assert not str(value).endswith("/api/v1"), f"{key} must not end in /api/v1"


def test_env_contract_drops_legacy_vars_from_inherited_env():
    env = _common.env_contract(
        "test-agent-key",
        base_env={
            "COGNEE_SERVICE_URL": "http://127.0.0.1:8000/api/v1",
            "TRANSPORT_MODE": "stdio",
        },
    )
    assert "COGNEE_SERVICE_URL" not in env
    assert "TRANSPORT_MODE" not in env
    assert env["COGNEE_BASE_URL"] == "http://127.0.0.1:8000"


# --- 2. uvx resolver ---------------------------------------------------

def test_resolve_uvx_uses_path_when_present(tmp_path, monkeypatch):
    fake = tmp_path / "uvx"
    fake.write_text("#!/bin/sh\ntrue\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert _common.resolve_uvx() == str(fake)


def test_resolve_uvx_falls_back_to_local_bin_when_not_on_path(tmp_path, monkeypatch):
    # empty dir on PATH: no uvx found -> absolute per-user install path
    monkeypatch.setenv("PATH", str(tmp_path))
    got = _common.resolve_uvx()
    expected = os.path.join(os.path.expanduser("~"), ".local", "bin", "uvx")
    assert got == expected
    assert os.path.isabs(got)


def test_default_uvx_fallback_is_local_bin_path():
    p = _common.DEFAULT_UVX
    assert os.path.isabs(p)
    assert p.endswith(os.path.join(".local", "bin", "uvx"))
    # the fallback is EXPANDED at runtime, never hardcoded in source
    # (the source-scan test above is what enforces the PII rule)
    assert "expanduser" in read("_common.py")


def test_bridge_pin_is_pinned():
    assert _common.COGNEE_MCP_PIN == UVX_PIN


# --- 3. credential/dataset sources + source hygiene ---------------------

def test_load_cred_reads_api_key(tmp_path):
    cred = tmp_path / "agent-cred.json"
    cred.write_text(json.dumps({"api_key": "sk-test-only"}))
    assert _common.load_cred(str(cred)) == "sk-test-only"


def test_probe_modules_expose_main_and_import_side_effect_free():
    for mod in (mcp_probe, mcp_names, mcp_agentmem, curl_tier2):
        assert callable(mod.main)  # importing must not have launched anything


def test_probes_build_env_via_shared_contract():
    for name in ("mcp_probe.py", "mcp_names.py", "mcp_agentmem.py"):
        src = read(name)
        assert "_common.env_contract" in src, f"{name}: must use the shared contract"
        assert "COGNEE_SERVICE_URL" not in src, f"{name}: legacy serve()-path var"


def test_sources_contain_no_pii_literals():
    for name in ALL_SOURCES:
        src = read(name)
        assert not PII_RE.search(src), f"{name}: PII literal found"


def test_sources_contain_no_email_like_dataset_names():
    for name in ALL_SOURCES:
        src = read(name).replace(UVX_PIN, "")  # version pin is not a dataset name
        assert not EMAIL_RE.search(src), f"{name}: email-like literal found"


def test_credential_paths_and_datasets_come_from_argv_or_env():
    for name in PROBE_SCRIPTS:
        src = read(name)
        assert "sys.argv" in src, f"{name}: inputs must come from argv"
        assert not re.search(r"open\(\s*[\"']", src), f"{name}: hardcoded open() path"
        # no quoted raw-API path literal (".../api/v1/...") in the bridge
        # probes; only the raw-HTTP probe constructs API paths
        assert not re.search(r"[\"']/api/v1/", src) or name == "curl_tier2.py", \
            f"{name}: raw API paths belong in _common / curl_tier2, not the probe"
