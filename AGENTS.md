# AGENTS.md — cognee-team

Multi-tenant memory API built on `cognee`. Auth is **always enforced**, tenant
isolation always on; the privacy contract is a **tiered ACL** (public / team /
private-per-member) with unsafe AI agents partitioned with their owning member.
Everything bootstrap grants + verify asserts is defined in `tiers.py` + `roster.json`.

## Build / test / run

```bash
cd ~/1/cognee-team
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
- `bootstrap.py` re-run reuses existing bootstrap keys; only `--reset-keys` mints new ones
  (and invalidates the old — run with the server stopped).
- `DEFAULT_USER_PASSWORD` is **deliberately unset** (`.env`) — the default superuser
  account is not loginable; auth is by API key / per-user password.
- To re-point a client after a key reset: read the key from `credentials/<email>.json`
  and run `install_client.sh` again.

## Conventions

- **`tiers.py` is the source of truth** for the ACL matrix (`ROLE_MATRIX`) + principal
  emails (from `roster.json`). Change the matrix there, re-run `bootstrap.py`, re-run
  `verify.py`.
- ACL grants go to **ROLES**, never the tenant principal (a tenant grant would leak to
  agent members). Per-agent private grants are direct, on the owner's dataset only.
- `verify.py` is the negative-space proof: agents must NOT see team or other members'
  private tiers; the default superuser must NOT log in.

## Current state (2026-10-11, proof in `~/1/proof/cognee/`)

- Core ACL job **VERIFIED-LIVE at T4**: `verify.py` → ALL CHECKS PASSED (live vs :8000).
- **D1 (stale client key) RESOLVED**: `cogctl me`/`list` now 200 (client re-pointed at the
  live `credentials/jlam@unistra.fr.json` key via `install_client.sh`). See
  `proof1b_client_repoint.txt`.
- **D2 (data-root drift) — documented-accepted, NOT a functional defect.** `.env`
  `SYSTEM_ROOT_DIRECTORY=/home/jlam/cognee-team/data` (pre-move path); repo is at
  `~/1/cognee-team`. Service works (data lands at the old path). Owner documented-accepted
  it in commit `fca11ae`. Optional safe consolidation (owner sign-off; stops the live,
  actively-written service): stop service → `cp -a ~/cognee-team/data/* ~/1/cognee-team/
  data/` → repoint `SYSTEM_ROOT_DIRECTORY`/`COGNEE_LOGS_DIR`/`COGNEE_REPOS_DIR` in `.env`
  to `~/1/cognee-team/data` → start → `verify.py` 19/19.
