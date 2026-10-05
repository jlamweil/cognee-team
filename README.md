# cognee-team — team knowledge memory with tiered access for unsafe AI providers

Self-hosted [cognee](https://github.com/topoteretes/cognee) (pinned 1.6.2) with
a provably-enforced partitioning: one tenant, tiered datasets, and per-provider
principals for AI agent providers that have **no zero-data-retention (no-ZDR)**
guarantees.

## Security model (single source of truth: `tiers.py`)

| tier | dataset | members (humans) | agent providers (per-member) |
|---|---|---|---|
| public | `public` | read + write | **read + write** (all agents) |
| team | `team` | read + write | **nothing** (403 everywhere) |
| private | `private/<member>` | owner full | **owner's OWN agents: read + write**; every other agent: nothing (403) |

Roster (`roster.json`) maps each member to their own providers via
`member_agents`. A person's own AI can work their private projects; the tier
stays invisible to every other member, agent, and the admin. Agents of member M
are created with `parent_user_id = M` — anything an agent ingests into its own
scratch datasets is inherited downward by M only.

- **Isolation is enforced by cognee, not by convention.** `ENABLE_BACKEND_ACCESS_CONTROL=true`
  + `REQUIRE_AUTHENTICATION=true` are pinned in `.env`; every dataset carries a
  tenant stamp and every recall is filtered by *active tenant + explicit ACL
  grants*. Tenants start with zero permissions; grants flow only through the
  `member` / `agent-provider` ROLES or explicit per-principal grants (the
  owner-private grants) — never through the tenant principal
  (a tenant grant would leak to agents too; see the OPERATOR RULE in `tiers.py`).
- **No-ZDR rationale.** The risk of a no-ZDR provider is content *flowing out*
  into retained context. Agents can only ever resolve `public` + their **own
  member's** private tier (visibility, read, and write are all verified
  403/200 in `verify.py`), so retained context can never contain other
  members' material.
- **Names resolve only against caller-owned datasets** (cognee rule). A shared
  dataset must be addressed by UUID — one more wall against accidental access.
- **The auto-created default superuser has no password and cannot log in.**

## Layout

```
cognee-team/
  .env                 posture, storage, LLM/embedding config (gitignored)
  tiers.py             THE matrix: principals, roles, datasets, grants
  bootstrap.py         idempotent provisioning (LLM-free; run server-stopped)
  verify.py            19 hard assertions against the live API
  demo_agent_recall.py E2E: agent pulls public chunk, denied on team
  cognify_seed.py      one-time graph build for seeded datasets
  run_api.sh           server launcher (systemd calls this)
  systemd/cognee-team-api.service
  mcp/README.md        how agents connect over MCP
  credentials/         per-principal email/password/API keys (chmod 600, gitignored)
  data/                SQLite + LanceDB + Kuzu state (gitignored)
```

## Daily operation

```bash
systemctl --user status cognee-team-api     # running? (enabled at boot)
systemctl --user restart cognee-team-api    # after .env / code changes
cd cognee-team && .venv/bin/python verify.py   # after ANY permission or config change
```

- **API:** `http://<host>:8000` (bind 0.0.0.0; set `COGNEE_BIND=127.0.0.1` in
  the unit for loopback-only). Auth: `X-Api-Key` header or JWT via
  `POST /api/v1/auth/login`.
- **Remember (write):** `POST /api/v1/add` (multipart `data` + `datasetId`) then
  `POST /api/v1/cognify` `{"dataset_ids":[...]}` — or `remember()` which does both.
- **Recall:** `POST /api/v1/search` with `dataset_ids` (UUIDs!) — see
  `demo_agent_recall.py` for the exact shapes.

## Adding a team member

1. `roster.json`: add their email to `member_emails`.
2. Server stopped: `systemctl --user stop cognee-team-api && .venv/bin/python bootstrap.py && systemctl --user start cognee-team-api`
3. `bootstrap.py` creates the user, tenant+role membership, `private/<email>`
   dataset, and a bootstrap API key in `credentials/<email>.json` (600).
4. `.venv/bin/python verify.py` — green, or stop.

## Onboarding an unsafe AI provider (per member)

Same flow, but add the provider email to that member's `member_agents` list in
`roster.json` (create the key if the member is new). One principal **per
provider**, never shared — the key is the revocation boundary. The provider is
created with parent = the owning member and gets: `public` (via the
`agent-provider` role) **plus the owner's `private/<owner>` (direct grants)**
— nothing else. Give the provider exactly its `credentials/<email>.json`
(`X-Api-Key`) and point it at `mcp/README.md`.

## Revoke a provider (or its write access)

```bash
# all access: delete its key (it dies immediately)
curl -X DELETE http://127.0.0.1:8000/api/v1/auth/api-keys/<key_id> -H "X-Api-Key: $ADMIN_KEY"
# write-only revoke on public (provider keeps read):
#   tiers.py: drop WRITE from AGENT_ROLE[public] -> re-run bootstrap -> verify.py
```

Bootstrap re-runs are idempotent; `--reset-keys` re-mints API keys.

## LLM stack (extraction quality vs. privacy)

Current **proven local** combo (`.env`): `custom` + `openai/qwen2.5:7b-instruct`
via Ollama's OpenAI-compatible `/v1` + `STRUCTURED_OUTPUT_FRAMEWORK=instructor`
+ `LLM_INSTRUCTOR_MODE=json_mode` + fastembed `bge-small-en-v1.5`. Do not mix
the ollama-provider `tool_call` path with these models — qwen echoes schemas in
tool mode; gemma3/llama3.2 fail schema discipline at these sizes.

For real quality (and when documents may leave the box only for *approved*
providers), swap in a preset at the bottom of `.env`:

- **Albert (etalab) gpt-oss-120b**: `LLM_PROVIDER=custom`, `LLM_ENDPOINT=https://albert.api.etalab.gouv.fr/v1`, `LLM_MODEL=openai/gpt-oss-120b`, `LLM_API_KEY=<key>`
- **Any other OpenAI-compatible endpoint** (organizational/campus LLM): same shape — set endpoint, model, key.

Restart, re-run `cognify_seed.py`, done. Cognify/recall costs scale with the
model; the 7b local path is minutes per query on CPU — the 120b remote path is
seconds. Extraction runs through cognee's LLM config only; ACLs are LLM-free.

## Pitfalls already paid for (do not rediscover)

- `add_user_to_tenant` does NOT set the **active tenant** — bootstrap must call
  `select_tenant` or every tenant-stamped dataset is invisible (first verify
  run failed exactly there). Private datasets must be created *after* the
  owner's `select_tenant`, or they get stamped tenant-less.
- Emails: `.local` is rejected by validation (`cognee-team.dev` placeholder).
- Embeddings: Ollama `/api/embed` with `truncate:false` 422s on >2048-token
  input — that's why embeddings are **fastembed** (in-process, splits by
  tokenizer). If you switch back to Ollama embeddings, expect graph-index
  failures on long edge summaries.
- JSON mode: a weak model echoes the JSON schema; use ≥7b instruct and
  `json_mode`, keep the default strict KnowledgeGraph schema.
- `LLM_ARGS={"parallel_tool_calls": false}` is load-bearing for qwen.
- `get_user_by_email` returns `None` (does not raise) for missing users.
- Search on an **ingest-only dataset is 404**, not 200-empty: cognee 1.6.2
  raises `NoDataError` ("knowledge graph is empty; run cognify") AFTER the
  permission check. verify.py therefore treats 200 **or 404** as read-granted
  on permitted datasets; 403 remains the only denial signal (and the strict
  expectation on forbidden ones). Fresh bootstrap -> verify passes with no
  cognify; cognify only adds real recall content.
- Ollama **memory wall**: qwen2.5:7b needs ~5.5 GiB and the runner showed
  `--parallel 4` (OLLAMA_NUM_PARALLEL default multiplies KV-cache RAM). Under
  desktop load the load 422s with "model requires more system memory (5.4 GiB)
  than is available" — and the failed cognify can leave a **stuck runner** at
  ~400% CPU holding the 5.5 GiB indefinitely. Remedy: `ollama stop
  qwen2.5:7b-instruct` (or `ollama ps` to spot the zombie), free RAM, retry
  cognify. Check `free -h` before cognify; close memory-hungry apps first.
- Data lives in `cognee-team/data` via `SYSTEM_ROOT_DIRECTORY`; the default is
  inside site-packages and dies with the venv.

## Verification story

`verify.py` asserts, per principal, against the live API with real credentials:
visibility (datasets list), read (CHUNKS search), write (add), JWT login, and
the default-user posture. `demo_agent_recall.py` is the human-readable E2E.
Run both after any change to tiers, grants, or cognee upgrades. Exit 0 = ship.
