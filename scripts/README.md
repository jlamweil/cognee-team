# MCP diagnostic probes

Parameterized probes for the team-memory MCP bridge (`uvx
cognee-mcp@0.5.7`, pinned) and the raw-HTTP tier API. All interpreters: the
repo venv python (`.venv/bin/python`). Credential JSON files are passed as
argv paths; files are opened, never echoed — key material is not printed.

Shared helper: `_common.py` — the client-mode env contract builder
(`COGNEE_BASE_URL=http://127.0.0.1:8000` with NO `/api/v1` suffix,
`COGNEE_API_AUTH_SCHEME=x-api-key`, `COGNEE_API_KEY` from the credential
file — the serve()-path variable is never set) and the uvx resolver
(`shutil.which("uvx")`, falling back to the absolute `~/.local/bin/uvx`).

## mcp_probe.py — bridge smoke (read-only)

Spawns the bridge, performs the MCP handshake, lists tools. No tools/call.

```bash
.venv/bin/python scripts/mcp_probe.py <agent-cred.json>
```

Expected output (scrubbed):

```
INIT result: { "protocolVersion": "...", "serverInfo": { "name": "cognee-mcp", "version": "0.5.7" } }
TOOL_COUNT: 6
- remember: ...
- recall: ...
- forget: ...
- code_search: ...
- search_tools: ...
- call_tool: ...
```

## mcp_names.py — recall BY NAME through the bridge

The client sends dataset names only; the server resolves names among the
caller's OWN datasets. Probes the caller's own datasets by name (or the
names passed as args) plus the bare-recall fallback.

```bash
.venv/bin/python scripts/mcp_names.py <agent-cred.json> [dataset-name ...]
```

(no name args → the caller's own dataset listing is probed by name)

Expected output: `MCP name=<dataset-name>: ...` lines plus
`MCP bare recall: ...`. Recall by name on a SHARED tier →
`DatasetNotFoundError` 404: expected, not a bug (use raw HTTP
`dataset_ids` for shared tiers).

## mcp_agentmem.py — per-agent memory loop

remember → list datasets → recall by name → forget (cleanup). The agent
owns its auto-scoped dataset, so by-name resolution works through the
bridge. The probe note is overridable via the `COGNEE_PROBE_NOTE` env var.

```bash
.venv/bin/python scripts/mcp_agentmem.py <agent-cred.json>
```

Expected output: `REMEMBER: ... | isError= ...`,
`NEW DATASET(S) SEEN BY AGENT: [...]`,
`RECALL by name='<dataset-name>': ... | NOTE_FOUND= True`,
`FORGET cleanup: ...`. First `remember` may hit a 409 ingest-lock →
restart the service, retry once.

## curl_tier2.py — raw-HTTP tier matrix (dataset_ids)

Resolves dataset UUIDs through the admin dataset listing (names are never
hardcoded in source), then POSTs `/api/v1/recall` per tier.

```bash
.venv/bin/python scripts/curl_tier2.py <agent-cred.json> <admin-cred.json> [dataset-name ...]
```

(no name args → public + team + every `private/*` dataset in the listing)

Expected output (content-independent; `team == 403` is the load-bearing
invariant):

```
AGENT public       http=200 blocked=False :: ...
AGENT team         http=403 blocked=True  :: PermissionDeniedError [read]
AGENT private/<owner>  http=404 blocked=False :: (empty recall)
ADMIN public       http=200 blocked=False :: ...
```

## Failure interpretation (observed live)

| Symptom | Cause | Fix |
|---|---|---|
| 401 `Authentication required…` | default Bearer scheme | set `COGNEE_API_AUTH_SCHEME=x-api-key` |
| 404 on `/api/v1/api/v1/recall` | base URL carries `/api/v1` (or the serve()-path variable was used) | `COGNEE_BASE_URL=http://127.0.0.1:8000` (no suffix) |
| 404 `Dataset(s) not found…` via MCP by name | names-only client vs caller-owned resolution | expected for shared tiers; raw HTTP `dataset_ids`; per-agent datasets work |
| bridge spawn dies: `uvx: not found` | spawned PATH lacks the uvx bin dir | probes resolve uvx via PATH with the absolute `~/.local/bin/uvx` fallback; client entries should use the absolute path |
| 409 on first `remember` | ingest-lock | restart the service, retry once |
| recall content `build_failed …` OOM | box memory (out of scope) | assert name resolution/ACL, not content; `search_type: CHUNKS` |
| `team == 403` | expected — negative-space ACL | not a bug |
| client timeout, bridge never answers | cold uvx env build > handshake timeout | pre-warm the pin; allow a longer client timeout |
