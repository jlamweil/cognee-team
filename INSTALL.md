# Install & access — cognee-team memory

## Where things live (server = the machine running install_server.sh)

| what | path |
|---|---|
| Code, scripts, docs | `<root>/` (anywhere, e.g. `/srv/cognee-team`) |
| Python env (cognee 1.6.2 + uv, ~1.2 GB) | `<root>/.venv/` |
| All memory data (SQLite ACLs, LanceDB vectors, Kuzu graphs) | `<root>/data/` |
| Per-principal API keys (chmod 600) | `<root>/credentials/` |
| systemd user unit | ``~/.config/systemd/user/cognee-team-api.service` (written by `install_server.sh`)` |

Server address: `http://<server-host>:8000` (auth required on every call).

## What does anyone need to install?

**Raw cognee? No — nobody.** Cognee runs *only* on the server. Clients are
plain HTTP/MCP consumers.

| role | installs | command |
|---|---|---|
| Server admin (one box) | this folder + uv + cognee[api] via installer | see below |
| Team member | **nothing** — just curl, or `cogctl` from install_client.sh | see below |
| AI agent provider | **nothing** — MCP config pointing at the server | see below |

## Server install (one command, idempotent)

```bash
cd cognee-team
./install_server.sh --root /srv/cognee-team --ollama
```

Does: uv → code sync → venv + `cognee[api]` + fastembed → `.env` from template
(generated JWT secrets) → Ollama model pull → `bootstrap.py` (all users, roles,
tier datasets, ACL grants, API keys) → systemd unit install+start → `verify.py`
(19 checks). Exit 0 = enforced and green.

Afterwards: edit `roster.json` (`member_emails` / `member_agents`), then
`systemctl --user stop cognee-team-api && .venv/bin/python bootstrap.py &&
systemctl --user start cognee-team-api && .venv/bin/python verify.py`.

## Team member setup (30 seconds)

```bash
./install_client.sh http://<server-host>:8000 <api-key-from-admin>
cogctl list                          # datasets you can see
cogctl recall "query" <dataset-uuid> # search (CHUNKS, no LLM)
cogctl store notes.md public         # add to a tier you can write
cogctl me
```

Installs `uv` + `cognee-mcp` (as client tooling only) and a `cogctl` wrapper;
config in `~/.config/cogctl.json` (600). **No cognee install, no venv.**
Your API key IS your identity — per-person keys, per-person revocation.

## AI agent provider setup (the unsafe, no-ZDR ones)

No install. MCP client config (works with any MCP-capable agent):

```json
{
  "mcpServers": {
    "team-memory": {
      "command": "uvx",
      "args": ["cognee-mcp"],
      "env": {
        "TRANSPORT_MODE": "stdio",
        "COGNEE_SERVICE_URL": "http://<server-host>:8000/api/v1",
        "COGNEE_API_KEY": "<that-provider's-own-key>"
      }
    }
  }
}
```

One key per provider — never shared. Full details: `mcp/README.md`.

## Security model recap (single source of truth: `tiers.py`)

| tier | members | own providers | other providers |
|---|---|---|---|
| `public` | read+write | read+write | read+write |
| `team` | read+write | 403 everything | 403 everything |
| `private/<member>` | owner only | **owner's agents: rw** | 403 everything |

Each member maps their own providers in `roster.json` → `member_agents`.
Enforced server-side by cognee ACLs (`ENABLE_BACKEND_ACCESS_CONTROL=true`,
`REQUIRE_AUTHENTICATION=true` — pinned in `.env`). An agent can only ever pull
`public` + its owner's private tier into its (retained) context — that is the
whole point. After ANY change: `verify.py` must exit 0.

## LLM on the server (extraction)

Proven local default: Ollama `qwen2.5:7b-instruct` (installer `--ollama` pulls
it; ~5 GB RAM; CPU-speed cognify). For quality, switch `.env` to the commented
Albert (etalab) `gpt-oss-120b` or any other OpenAI-compatible preset, restart,
re-run `cognify_seed.py`. Embeddings are in-process fastembed — always local.
