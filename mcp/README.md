# MCP access for AI agent providers

Each unsafe provider gets its **own** principal (user + API key in
`credentials/<email>.json`), registered under its **owning member** in
`roster.json` (`member_agents`). Never share one key between providers — the key
IS the security boundary, so per-provider keys are what makes per-provider
revocation possible.

## What the provider's principal can do

Exactly what `tiers.py` grants its principal: read + write on `public` (via
the `agent-provider` role) **plus read + write on its owner's
`private/<owner>`** (direct grants). Team and every OTHER member's private
datasets return 403 for every call — verified by `../verify.py`.

## Stdio MCP client config (agents running on this box)

Run the official `cognee-mcp` package with the provider's identity via env:

```json
{
  "mcpServers": {
    "team-memory": {
      "command": "uvx",
      "args": ["cognee-mcp"],
      "env": {
        "TRANSPORT_MODE": "stdio",
        "COGNEE_SERVICE_URL": "http://127.0.0.1:8000/api/v1",
        "COGNEE_API_KEY": "<provider's api key from credentials/<email>.json>"
      }
    }
  }
}
```

The MCP server proxies to the team API with that key, so every tool call is
authenticated AND tier-scoped as the provider principal — identical to what
raw HTTP callers get.

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
