# AGENTS.md — cognee-team

Multi-tenant memory API built on `cognee`. Auth is **always enforced**, tenant
isolation always on; the privacy contract is a **tiered ACL** (public / team /
private-per-member, plus a safe-only `private-safe` split) — unsafe AI agents
are partitioned with their owning member, and safe (ZDR) providers (the
`safe-provider` role) additionally reach `team` and the owner's `private-safe`.
Everything bootstrap grants + verify asserts is defined in `tiers.py` + `roster.json`.

## Build / test / run

```bash
cd cognee-team
.venv/bin/python verify.py            # THE proof: live ACL matrix vs :8000 (19 checks, T4)
.venv/bin/python bootstrap.py         # idempotent, offline, LLM-free; server STOPPED;
                                      #   reuses existing "bootstrap" keys; --reset-keys re-mints
./run_api.sh                          # start the API (cwd must be here so ./.env loads)
```

- **Server** (user systemd): `systemctl --user status cognee-team-api.service`
  (`run_api.sh` → `uvicorn cognee.api.client:app --port 8000`).
- **Client** (`cogctl`): `me | list | recall "q" <uuid> | store <file> <uuid>`.
  Setup: `./install_client.sh http://<host>:8000 <api-key>` → `~/.config/cogctl.json`.

## Auth model (load-bearing)

- One **"bootstrap" API key per principal**, stored in `credentials/<email>.json`
  (chmod 600). The raw key is only recoverable from `credentials/`.
- `bootstrap.py` re-run reuses existing bootstrap keys; only `--reset-keys` mints new
  ones (run with the server stopped). Re-mint is **additive**: old keys STAY
  valid until explicitly revoked (`DELETE /api/v1/auth/api-keys/{id}` — see
  `mcp/README.md` rules); there is a 10-key cap per principal, so revoking
  after re-mint is part of rotation, not optional.
- `DEFAULT_USER_PASSWORD` is **deliberately unset** (`.env`) — the default superuser
  account is not loginable; auth is by API key / per-user password.
- To re-point a client after a key reset: read the key from `credentials/<email>.json`
  and run `install_client.sh` again.

## Conventions

- **`tiers.py` is the source of truth** for the ACL matrix (`ROLE_MATRIX`) + principal
  emails (from `roster.json`). Change the matrix there, re-run `bootstrap.py`, re-run
  `verify.py`.
- ACL grants go to **ROLES** (`member`, `agent-provider`, `safe-provider`), never the
  tenant principal (a tenant grant would leak to agent members). Per-agent private
  grants are direct on the owner's `private/<owner>`; per-safe-provider grants also
  cover the owner's safe-only `private-safe/<owner>` (unsafe agents get nothing on it).
- `verify.py` is the negative-space proof: unsafe agents must NOT see team, other
  members' private tiers, or the owner's `private-safe` (safe agents DO see `team`
  + both private tiers); the default superuser must NOT log in.

## Current state

- Verification is `.venv/bin/python verify.py` — the live ACL battery against
  `:8000` (per-principal hard assertions); last run green (all checks passed).
- The data root is the repo's own (gitignored) `data/` dir, set via
  `SYSTEM_ROOT_DIRECTORY` in `.env` (with `COGNEE_LOGS_DIR`/`COGNEE_REPOS_DIR`);
  an older data-root drift to a data dir outside the repo was resolved 2026-10-12
  (migrated into `data/` and re-verified).
