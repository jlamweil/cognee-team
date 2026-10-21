# cognee-team — team knowledge memory with tiered access for AI providers

Self-hosted [cognee](https://github.com/topoteretes/cognee) (pinned 1.6.2) with
a provably-enforced partitioning: one tenant, tiered datasets, and per-provider
principals for AI agent providers — both the **unsafe (no-ZDR)** ones, confined
to `public` + their owner's `private`, and the **safe (ZDR)** ones, which
additionally reach the `team` tier.

> Ops/verification: `verify.py` against the live API — data-root and tunnel gotchas are in "Pitfalls already paid for" below.

## What this is, and why

cognee-team is a self-hosted memory backend shared by a team of humans and a
team of AI agents, with access strictly tiered so that an AI provider that
*retains* the data it sees (no zero-data-retention / no-ZDR) can never be fed
material it should not keep.

One-sentence pitch: your agents get **read** on the **public** tier and
**read/write** on their **own owner's private** tier, and a hard 403 everywhere
else — enforced by the database, not by a prompt. If a provider logs or trains
on what it is given, the worst it can retain is material its owner already owns;
agents are read-only on `public`, so nothing they read can be written back to it.
Providers with a zero-data-retention guarantee (the **safe** tier) additionally
get read+write on the `team` tier and their owner's `private-safe` tier; see the
security-model table.

Who it's for: small teams that want one shared, queryable memory for people and
agents, where some agents run through third-party providers you do not fully
trust with your data. If every one of your agents is zero-data-retention, plain
[cognee](https://github.com/topoteretes/cognee) is enough and you do not need this.

## Security model (single source of truth: `tiers.py`)

| tier | dataset | members (humans) | unsafe agents (per-member) | safe agents (per-member, ZDR) |
|---|---|---|---|---|
| public | `public` | read + write | **read only** | **read only** |
| team | `team` | read + write | **nothing** (403 everywhere) | **read + write** |
| private | `private/<member>` | owner full | **owner's OWN agents: read + write**; every other agent: nothing (403) | **owner's OWN safe agents: read only** (writes go to private-safe); every other: nothing (403) |
| private-safe | `private-safe/<member>` | owner full | **nothing** (403 everywhere) | **owner's OWN safe agents: read + write**; every other: nothing (403) |

Roster (`roster.json`) maps each member to their own providers via
`member_agents` (unsafe, no-ZDR) and `member_safe_agents` (safe, ZDR). A
person's own AI can work their private projects; the tier stays invisible to
every other member, agent, and the admin. Agents of member M are created with
`parent_user_id = M` — anything an agent ingests into its own scratch datasets
is inherited downward by M only. Each member has **two** private tiers:
`private/<member>` (unsafe-allowed — unsafe agents get rw here; safe agents get
read-only, their private writes go to private-safe) and `private-safe/<member>`
(safe-only — only ZDR providers reach it, rw). Safe providers get the same
partitioning as unsafe ones, plus `team` (rw) and the owner's `private-safe`
tier (rw) — read-only on `public` like every agent.

- **Isolation is enforced by cognee, not by convention.** `ENABLE_BACKEND_ACCESS_CONTROL=true`
  + `REQUIRE_AUTHENTICATION=true` are pinned in `.env`; every dataset carries a
  tenant stamp and every recall is filtered by *active tenant + explicit ACL
  grants*. Tenants start with zero permissions; grants flow only through the
  `member` / `agent-provider` / `safe-provider` ROLES or explicit per-principal grants (the
  owner-private grants) — never through the tenant principal
  (a tenant grant would leak to agents too; see the OPERATOR RULE in `tiers.py`).
- **No-ZDR rationale.** The risk of a no-ZDR provider is content *flowing out*
  into retained context. Agents can only ever read `public` and their **own
  member's** private tier, and can only write their own member's private tier
  (safe agents: only the owner's `private-safe`) — `public` is read-only for
  every agent, so retained context can never contain other members' material and
  can never be composed back into `public`. Visibility, read, and write are all
  asserted 200/403 in `verify.py`.
- **Names resolve only against caller-owned datasets** (cognee rule). A shared
  dataset must be addressed by UUID — one more wall against accidental access.
- **The auto-created default superuser has no password and cannot log in.**

## Layout

```
cognee-team/
  .env                 posture, storage, LLM/embedding config (gitignored)
  tiers.py             THE matrix: principals, roles, datasets, grants
   bootstrap.py         idempotent provisioning + reconcile (LLM-free; server-stopped)
   verify.py            per-principal hard assertions against the live API
   scripts/dump_acl.py  read-only effective read/write footprint + before/after diff
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

 - **Inspect grants:** `.venv/bin/python scripts/dump_acl.py` prints each
   principal's effective read/write sets; `--json snap.json` then `--diff
   snap.json` give before/after evidence. `bootstrap.py` now reconciles the
   managed ACL to `tiers.py` (revokes drift); `--reconcile-dry-run` previews it.
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

## Onboarding a safe (ZDR) provider (per member)

Identical flow, but register the provider in the member's `member_safe_agents`
list instead of `member_agents`. One principal **per provider**, never shared —
the key is the revocation boundary. The provider is created with parent = the
owning member and gets: `public` (**read only**, via the `safe-provider` role)
**plus the owner's `private/<owner>` (read only, direct grant) and
`private-safe/<owner>` (read + write, direct grant) plus `team` (read + write,
via the role)** — nothing else. Everything else is identical to the
unsafe path; give it its `credentials/<email>.json` (`X-Api-Key`) and point it
at `mcp/README.md`.

## Revoke a provider (or its write access)

```bash
# all access: delete its key (it dies immediately)
curl -X DELETE http://127.0.0.1:8000/api/v1/auth/api-keys/<key_id> -H "X-Api-Key: $ADMIN_KEY"
```

Providers are **read-only on `public` by default** — there is nothing to revoke
there. To deliberately grant one of them public write (which re-opens the
private → public leak), add `WRITE` to that role's `public` entry in `tiers.py`,
re-run `bootstrap.py` (the reconciliation grants it), then re-run `verify.py`.

Bootstrap re-runs are idempotent and **reconcile** the managed grants to
`tiers.py` (revoking drift); `--reset-keys` re-mints API keys.

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
  Permanent fix (operator, needs sudo): `systemctl edit ollama` →
  `[Service]` / `Environment=OLLAMA_NUM_PARALLEL=1` / `OLLAMA_MAX_LOADED_MODELS=1`,
  then `systemctl restart ollama` — cuts KV-cache RAM ~4x and prevents the
  stuck-runner state at the source.
- Data lives in `./data` (the repo's own dir) via `SYSTEM_ROOT_DIRECTORY`; the
  default location is inside site-packages and dies with the venv.
- **Data-root drift (consolidated, 2026-10-12)**: the data root was at one point
  an older data dir *outside* the repo, and `.env` still pointed
  `SYSTEM_ROOT_DIRECTORY` at that older path (where the live datasets actually
  lived; the service was verified green against it). It is now consolidated at
  the repo's own `data/` dir. Do not repoint `.env` at a different dir without
  first migrating the live data directory (rsync/cp -a, integrity check,
  restart, re-verify).

## Verification story

`verify.py` asserts, per principal, against the live API with real credentials:
visibility (datasets list), read (CHUNKS search), **write (add) — including the
negative space, where agents get a hard 403 writing `public` (and safe agents a
403 on the owner's `private`)** — JWT login, and the default-user posture.
`demo_agent_recall.py` is the human-readable E2E. Run both after any change to
tiers, grants, or cognee upgrades. Exit 0 = ship.

## License

MIT — see [LICENSE](LICENSE).
