# MCP access for AI agent providers

Each provider gets its **own** principal (user + API key in
`credentials/<email>.json`), registered under its **owning member** in
`roster.json` — unsafe (no-ZDR) providers under `member_agents` (role
`agent-provider`), safe (ZDR) providers under `member_safe_agents` (role
`safe-provider`). Safe providers connect **identically** but may additionally
reach the `team` tier. Never share one key between providers — the key
IS the security boundary, so per-provider keys are what makes per-provider
revocation possible.

## What the provider's principal can do

Exactly what `tiers.py` grants its principal: read + write on `public` (via
the `agent-provider` role for unsafe providers, the `safe-provider` role for
safe ones) **plus read + write on its owner's `private/<owner>`** (direct
grants). For **unsafe** providers, `team` and every OTHER member's private
datasets return 403 for every call. For **safe** (ZDR) providers, `team` is
readable and writable (via the `safe-provider` role) and only the OTHER
members' private datasets return 403 — verified by `../verify.py`.

## Stdio MCP client config (agents running on this box)

Run the official `cognee-mcp` package with the provider's identity. The
client-mode env contract (exact) and the pinned bridge launch:

```bash
COGNEE_BASE_URL=http://127.0.0.1:8000        # NO /api/v1 suffix (client appends paths)
COGNEE_API_AUTH_SCHEME=x-api-key              # bare Bearer → 401
COGNEE_API_KEY=<per-principal agent key>      # never member/admin keys
```

Bridge launch: `uvx cognee-mcp@0.5.7` (pinned — do not float the version).

Client config shape (JSON, e.g. for a pi-style `mcpServers` block):

```json
{
  "mcpServers": {
    "team-memory": {
      "command": "uvx",
      "args": ["cognee-mcp@0.5.7"],
      "env": {
        "COGNEE_BASE_URL": "http://127.0.0.1:8000",
        "COGNEE_API_AUTH_SCHEME": "x-api-key",
        "COGNEE_API_KEY": "<per-principal agent key>"
      }
    }
  }
}
```

The MCP server proxies to the team API with that key, so every tool call is
authenticated AND tier-scoped as the provider principal — identical to what
raw HTTP callers get.

### Concrete client entries (verified patterns)

**opencode** — `~/.config/opencode/opencode.json`, `mcp` block. Note the
expansion rules: opencode substitutes only `{env:VAR}` and `{file:path}` in
config values — shell-style `${VAR}`/`$VAR` is NOT expanded — and MCP config
hot-reloads (no restart). Keep the key out of the config file: write the raw
key to a 600-mode file and reference it with `{file:}`:

```json
"team-memory": {
  "type": "local",
  "command": ["/absolute/path/to/uvx", "cognee-mcp@0.5.7"],
  "environment": {
    "COGNEE_BASE_URL": "http://127.0.0.1:8000",
    "COGNEE_API_AUTH_SCHEME": "x-api-key",
    "COGNEE_API_KEY": "{file:<600-mode key file holding the raw key>}"
  },
  "enabled": true,
  "timeout": 60000
}
```

Use the absolute uvx path (the spawner PATH is not trusted) and check status
with `opencode mcp list`.

**pi** — `~/.pi/agent/mcp.json`, `mcpServers` block. pi env values support
`${NAME}` (process env) and `!cmd` (executes the rest as a shell command and
uses its stdout). `!cmd` keeps the key out of the file and out of any
launch-context assumption:

```json
"team-memory": {
  "command": "/absolute/path/to/uvx",
  "args": ["cognee-mcp@0.5.7"],
  "env": {
    "COGNEE_BASE_URL": "http://127.0.0.1:8000",
    "COGNEE_API_AUTH_SCHEME": "x-api-key",
    "COGNEE_API_KEY": "!<one-liner printing the api_key field of the credential JSON>"
  }
}
```

Check status with `pi mcp list` (state, tools, errors; exits 1 on failure).

### Warnings

- COGNEE_SERVICE_URL is the variable for the serve() path (launching your own
  in-process server). It is the WRONG variable for talking to an external
  running service — client mode is driven by the COGNEE_BASE_URL contract
  above, and that base URL must not carry a /api/v1 suffix (the client
  appends API paths itself, so a suffixed base doubles them to
  /api/v1/api/v1/... and every call 404s).
- The x-api-key auth scheme is required: with the default bare Bearer scheme
  every call returns 401.
- Shared-tier dataset recall BY NAME through the bridge returns the
  documented `DatasetNotFoundError` 404 (expected, not a bug): the client
  sends dataset names only, and the server resolves names among the
  caller's OWN datasets only. Use raw HTTP with `dataset_ids` (UUIDs) for
  shared tiers; per-agent auto-scoped memory (remember → recall by name on
  the agent's own dataset) works through the bridge.

## HTTP clients (non-MCP)

```bash
curl -H "X-Api-Key: <key>" http://<host>:8000/api/v1/datasets
```

## CLI (cognee-cli)

```bash
COGNEE_API_URL=http://127.0.0.1:8000 COGNEE_API_KEY=<key> \
  uvx --from "cognee[api]" cognee-cli recall "query" --api-url http://127.0.0.1:8000 --api-key <key>
```

## Rules

1. Rotate/revoke: delete the key in the UI or `DELETE /api/v1/auth/api-keys/{id}`,
   then mint a new one. Access dies with the key.
2. If a provider misbehaves (graph poisoning), revoke its **write** grant:
   see ../README.md "Revoke a provider's write access".
3. Public + owner-private only: anything the provider should not be able to
   pull into its (retained, non-ZDR) context must never be added to `public`
   — or to the owner's private tier if it should stay agent-free.
