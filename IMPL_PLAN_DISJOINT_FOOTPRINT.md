# Implementation Plan — Disjoint read/write footprints (safe/unsafe tier model) — **v3 (minimal-risk)**

> **STATUS: PLAN ONLY. No implementation yet.** This is **v3**, replacing v2
> (2026-10-20). It incorporates the adversarial review (v2) **and** a scope
> decision: **minimal risk**.
>
> **Resolved model:** a provider reads **all tiers its class is permitted to
> read** (maximal memory) but **can never write `public`** — publishing to
> `public` is a **human (owner) action**. Because no agent holds `write` on
> `public` in *any* context, the private→public leak is **impossible in every
> project and session** — so **no per-context credentials, no session scoping,
> and no harness changes** are needed. The fix is a **write-set restriction**
> on the *existing* per-provider credentials, plus a reconciliation step to
> remove the excess grants.
>
> **Dropped vs v2:** per-context principal provisioning (v2 C5/C6a/C6b/C7/C8),
> the session-scoping resolver (v2 C9), and per-project MCP enable/disable.
> **Kept:** reconciliation (C3), the write-set matrix change (C4), `verify.py`,
> debug tooling, and the API anchors.

---

## 1. Goal

Block a memory-writing LLM from publishing private-tier content into a lower
sensitivity tier (e.g. recall `private`, then `remember()` into `public`). Today
the ACL is symmetric `rw` per tier, so it is possible in practice (verified
live: recall private → compose → add public = 200).

**Minimal-risk fix:** give the agent's credential **no `write` grant on
`public`** (and nothing lower than its own private tier). The write gate
403s before any pipeline side-effect. The agent *reads* all it is class-permitted
to (maximal memory), but the dangerous write is **absent**, not merely
denied-by-policy. There is no reliance on session discipline or model behavior.

> **Accepted cost:** agents do **not** write to `public`. Publishing to
> `public` is a **human (owner)** action. If an agent must later publish public,
> that is a scope change (see §9 / §10 — it would reintroduce per-context +
> session scoping).

### 1.1 Two orthogonal axes (both required)

| Axis | Controls | Where |
|------|----------|-------|
| **safe / unsafe** | *where tokens go* (provider ZDR) | already built: `safe-provider` role + `private-safe/<owner>` tier |
| **write restriction** | *what an agent can publish* | **this plan**: agent write-set excludes `public` (and lower) |

ZDR protects the provider, not the publish path; the write restriction protects
the publish path. Both compose.

### 1.2 Verified evidence (unchanged from v2; state restored, `verify.py` ALL PASSED)

- **H1 — read & write enforced independently per dataset.** A principal granted
  *read-only* on a dataset got `search` → **200** and `add` → **403** on it. The crux.
- **H2 — multi-dataset recall spans a set** (all-permitted → 200).
- **H3 — recall is all-or-nothing** (any denied dataset → whole request **403**).
- **H4 — per-`(subject, dataset, permission)` grant rows** (grant read w/o write).
- **H5 — write gate 403s before pipeline side-effects** (fast, nothing written).
- **H6 — grants are live + reversible via API**; no restart, no code change.
- **H7 — tier write perms are role-inherited** (a principal's direct list can omit
  `public` while write still works via its role) — so removal needs reconciliation.

### 1.3 Dataset addressing: UUID vs. name

Cognee's write path (`add`/`remember`) resolves the target as:
- **By UUID** → gated on the caller's `write` grant for that exact dataset
  (`get_specific_user_permission_datasets(user, "write", ids)` → **403** before
  any pipeline side-effect). The only way to target a shared tier.
- **By name** → names resolve **only among the caller's own datasets**; an
  unmatched name **auto-creates a caller-owned dataset** (`load_or_create_datasets`).
  A name write can **never** target an admin-owned shared tier.

Consequences:
1. **Shared-tier read AND write are UUID-addressed.** A name-addressed
   `remember("public")` writes to the caller's own shadow dataset, not the shared
   tier. Tooling must pass **dataset UUIDs** for shared tiers.
2. **Own-namespace auto-create is *blessed*, not a leak.** It is owned by the
   caller; `create_authorized_dataset` grants the caller's `parent_user_id` (the
   **owner**) full perms. Inheritance flows **upward to the owner, never downward**
   to `public`/`team`. So the write-restriction below is stated over **shared-tier
   datasets**; effective write capability = {shared-tier write grants} ∪
   {own-namespace auto-create}, and the second term is allowed.

### 1.4 Why the restriction scopes to write only (delete/share ignored)

- **`delete`/`share` are ungranted on tier datasets.** `bootstrap.py` grants
  agents/roles only `read`+`write`; the only `delete`+`share` grants are the
  *owner-only* auto-grants in `create_authorized_dataset` (trusted publishers).
- **There is no move/transfer/rename-dataset API** in the cognee data routers.

Hence an agent cannot `share` a tier outward or exfiltrate via `delete`; the
write restriction is the whole of the publish surface. (Read is *intentionally*
maximal — that is the "memory shared maximally" requirement.)

---

## 2. Target model

One credential **per provider** (the existing principals — **no new per-context
principals**). Only the **write set** changes; read sets are unchanged (maximal
within each class).

| principal | class | read (unchanged) | **write (new)** |
|-----------|-------|------------------|-----------------|
| owner (human) | — | full: rw `public`,`team` + full `private/<o>`,`private-safe/<o>` | full (unchanged) |
| safe provider | safe | `public`,`team`,`private/<o>`,`private-safe/<o>` | **`private-safe/<o>`, `team`** |
| unsafe provider | unsafe | `public`,`private/<o>` | **`private/<o>`** |

**Delta from today (the only ACL change):**
- **All agents: remove `write` on `public`.** — the private→public leak, gone.
- **Safe agents: remove `write` on `private/<o>`.** — a safe agent writing
  `private/<o>` would make it readable by that owner's *unsafe* agents; it writes
  `private-safe/<o>` instead. *(Optional one-line: re-grant safe→`private/<o>`
  if you accept that exposure.)*
- **Safe agents keep `write` on `team`.** — team is safe-only (no unsafe/public
  exposure); this is the "write to team in a private context" decision.
- **Unsafe agents keep `write` on `private/<o>`** — their own owner's private tier.

**Why this is minimal risk:** no agent holds `write` on `public` in any context,
so private→public publish is impossible **regardless of project or session** —
no per-context credential, no session scoping, no residual. The only cross-tier
write an agent has is to its own (safe-only `team`/`private-safe`, or owner-private
`private`) tier.

**Harness: unchanged.** Each provider keeps its single `team-memory` MCP server
(same key, same base URL). No per-context servers, no per-project enable, no
resolver, no session scoping. (The v2 per-project MCP scoping is no longer needed.)

---

## 3. Gap analysis

| Need | Today | Gap |
|------|-------|-----|
| Remove agent `write` on `public` (and safe's on `private`) | `bootstrap.py` grants are **insert-only; never revokes** | **Reconciliation (C3)** to remove the excess write grants. |
| Prove the restricted write set | `verify.py` asserts rw per role | Extend: agents `write public → 403`; safe `write team/private-safe → 200`, `write private → 403`; unsafe `write private → 200` (C4). |
| Observe effective ACL | `curl_tier2.py` (keyword quirk) | `dump_acl.py` (C2). |
| Dead 3-tier abstraction | `tier_keys.*` / `check_tier_keys.py` (unreferenced) | remove-or-reconcile (C11). |

(Much smaller than v2 — no per-context provisioning, no CI roster context
placeholders, no harness scoping, no CI workflow change.)

---

## 4. Run durations

All server-side ops here are **SQLite-local**. `verify.py`, `bootstrap.py`, and
CI are **LLM-free**; only the extraction/cognify path and the production
`remember()` write are LLM-bound.

| Op | Command | LLM? | Estimate | Long? | Checkpointing |
|----|---------|------|----------|:-----:|---------------|
| ACL matrix probe | `verify.py` (raw `add`) | no (embeddings only) | **~30–60 s** | borderline | n/a (idempotent) |
| Bootstrap + reconcile (C3/C4) | `bootstrap.py --reconcile` | no | **< ~30 s** (a handful of revoke calls) | no | re-run safe (idempotent) |
| **Cognify (seed)** | `cognify_seed.py` → `POST /v1/cognify` | **yes** | **2–15 min / tier** | **YES** | **cognify ledger (§5)** |
| **Remember (prod write)** | `remember()` = add+cognify+improve | **yes** | **minutes / write** | **YES** | inherent to `remember`; debug via `add` |
| Key rotation | `bootstrap.py --reset-keys` | no | 5–30 s | no | additive + temp-then-rename |
| CI `verify-acl` | push/PR | no | 3–6 min (pip pinned stack) | borderline (CI) | n/a |

- **C1** adds `RUN_ID` + per-step `[elapsed]` + total to `bootstrap.py` and
  `cognify_seed.py`. Anything measured >~90 s gets a ledger (§5).
- Verify/debug use raw `add` (LLM-free), **not** `remember()`.

---

## 5. Checkpointing (long / interruptible ops)

Design rule: **any op that (a) is LLM-bound or (b) measured >~90 s writes a
per-unit ledger and resumes from the first un-done unit.** Ledgers are
gitignored under `data/`, JSON, `{unit: {status, ts, run_id, note}}`.

1. **Cognify ledger** — `data/cognify_ledger.json`, keyed by **tier**:
   - preflight: `free -h` + detect a **stuck in-flight cognify runner**; abort
     cleanly if stuck and log it.
   - **Pin `run_in_background=False`** (blocking) so a **200 means "done."** If
     `run_in_background=True` is ever used, a **202 means "still building"** —
     poll `GET /v1/datasets/status` to completion before writing `done`.
   - Record **entity/chunk counts**. A **blocking 200 with zero entities** is
     recorded **`failed` / `needs-review`**, not `done`, and is retried.
   - skip `status=done` tiers; cognify the rest; re-run resumes at the first
     non-`done` tier; a failed cognify is recorded `failed`, never implicit.
2. **Key rotation** — additive (old keys valid until revoked) → no hard failure
   window. Write each `credentials/<email>.json` to `.tmp` then `os.replace`
   (atomic); run with the server **stopped**; reconcile the 10-key cap.
3. **No provision ledger** — v3 creates **no new principals** (unlike v2), so
   provisioning is not a checkpoint concern.
4. **Every long op** emits `[run_id] step=… entity=… result=… [elapsed]`.

---

## 6. Debuggability

- **Structured logs** in `bootstrap.py` / `cognify_seed.py`: `run_id`, `step`,
  `entity`, `result`, keys truncated `raw[:8]****`. **No secrets/PII** in logs or
  ledgers.
- **Dry-run:** `bootstrap.py --reconcile --dry-run` → print the *would-revoke*
  delta (desired vs. actual), **zero** DB writes.
- **`scripts/dump_acl.py`** (new, read-only): for a credential (or all), print
  the effective read + write dataset sets (**direct + role**) **plus** live
  read/write probes (200/403/404 per dataset, raw `add`/`search` — no LLM).
  `--before`/`--after` → **state diff** of what a reconcile run changed.
  *(v1's `probe_footprint.py` stays **dropped** — redundant with `dump_acl.py`
  + `verify.py`.)*
- **`verify.py` remains the hard gate**; C4's disjoint-write assertions are a
  new section; existing checks preserved.
- **Rollback per milestone** is a documented, exact set of re-grant commands (§7).
- **Reproducible debug entrypoint**: `scripts/README.md` "debug a credential"
  recipe (dump_acl → targeted verify).

---

## 7. Atomic commit sequence

Each commit is **independently verifiable, revertible, and leaves `verify.py`
green** (or default-off). Order matters only where noted.

### Milestone 0 — Instrumentation & observation (no behavior change)

- **C0 — This plan (v3).**
  - *Verify:* `git diff --stat` docs-only; CI unaffected. *Rollback:* delete.
- **C1 — Timing + structured logging** in `bootstrap.py` + `cognify_seed.py`.
  - *Verify:* re-run bootstrap → `verify.py` green + duration line. *Rollback:* revert.
- **C2 — `scripts/dump_acl.py`** (read-only; reuse the verified
  grant/revoke/get + `get-user-id` patterns). **Do not add `probe_footprint.py`.**
  - *Verify:* run vs. live server → sensible output; `verify.py` unchanged. *Rollback:* delete.

### Milestone 1 — The fix (write-set restriction)

- **C3 — ACL reconciliation (load-bearing prerequisite).** Idempotent step in
  `bootstrap.py` that, **after** the insert-only grants, computes the **desired**
  grant set from `tiers.py` and **revokes** present-but-unwanted grants —
  **scoped to grants bootstrap manages** (role→shared datasets,
  per-agent→owner-private, per-safe→owner private + private-safe). It must not
  touch owner-created private-full grants. `--reconcile` (+ `--dry-run` prints
  the would-revoke delta, zero writes).
  - *Verify:* (a) **no-op** when matrix matches; (b) hand-grant one extra perm →
    re-run → it's revoked. *Rollback:* it only revokes what the matrix says;
    reverting the matrix re-grants on re-run. *Dur:* s–30 s. *Risk:* **MEDIUM
    over-revoke** — dry-run first, scope-limited, verify gate, exact rollback doc,
    test the revoke path on a hand-grant first.
- **C4 — Write-set matrix change + verify (THE fix).** `tiers.py` `ROLE_MATRIX`:
  safe → **read** public/team, **write** `private-safe`+`team` only (drop write
  public **and** write private); unsafe → **read** public/private, **write**
  `private` only (drop write public). Re-run `bootstrap.py` (C3 revokes the
  excess). `verify.py`: **both** safe + unsafe `write public → 403` (was 200);
  safe `write team → 200`, `write private-safe → 200`, `write private → 403`;
  unsafe `write private → 200`.
  - *Verify:* `verify.py` green incl. the flipped writes; live probe (safe **and**
    unsafe agent `recall private` 200, `add public` 403). *Rollback:* restore
    matrix + re-run (re-grants). *Dur:* s. *Risk:* LOW (fail-closed).
  - **C4 is green only with C3 present** (C3 removes the excess write grants).
    Land C3 then C4; they are the fix unit.

### Milestone 2 — Housekeeping

- **C5 — Docs / runbook.** `docs/disjoint-footprint-runbook.md` (provision /
  rotate / debug / rollback / the minimal-risk model / "owner publishes public");
  update `README.md`, `AGENTS.md`, `scripts/README.md`.
- **C11 — Remove-or-reconcile dead 3-tier abstraction** (independent).
  `check_tier_keys.py` + `tier_keys.template.json` + `tests/test_check_tier_keys.py`
  (and `tier_keys.local.json` if present) implement a 3-tier model that does not
  match the 4-tier ACL and is unreferenced. **Default: delete** (incl. its test);
  **Alt: reconcile** to 4-tier and wire in. *(Can land in M0 or M2.)*
  - *Verify:* `verify.py` green; `grep tier_keys` → clean. *Rollback:* revert.

**Dropped from v2:** C5–C8 (per-context provisioning + CI context placeholders)
and C9 (harness session scoping) — the minimal-risk model needs no per-context
credentials and no harness change.

---

## 8. Acceptance criteria ("done")

- Both safe + unsafe agents: **`write public → 403`**.
- Safe agent: `write team → 200`, `write private-safe → 200`, `write private → 403`.
- Unsafe agent: `write private → 200`, `write public → 403`.
- Owner (human): full rw unchanged (writes `public` fine).
- `verify.py` **ALL PASS**; no principal locked out; rollback proven.
- **No secrets or PII** in the repo, any log, or any ledger.

---

## 9. Decisions (resolved in v3) + accepted residuals

**Resolved:**
- **Minimal-risk model** — maximal read within class; agents **never** write
  `public`; **owner publishes public**. (Drops per-context + session scoping.)
- **Safe writes `private-safe` + `team`** (not `private/<o>`, to avoid unsafe
  exposure). *(Optional one-line: allow safe→`private/<o>` if accepted.)*
- **Harness unchanged** — no per-context servers, no per-project config, no
  resolver.
- `team` is not a distinct credential; its write is carried by the safe provider.

**Accepted residuals (all low / intentional):**
1. **private→team broadening** — a safe agent can publish private content to the
   safe-only `team` tier (you approved "write to team in private context"); no
   unsafe/public exposure.
2. **Provider retention** — an *unsafe* provider reading `private/<o>` sends it
   to a no-ZDR provider (the existing, intentional safe/unsafe split); use a safe
   provider for sensitive private work.
3. **Maximal memory** — the agent *sees* private content in-context (that is the
   requirement); the *publish* path is what's blocked, not the agent's knowledge.
4. **No agent public-writing** — the accepted cost; if needed later it
   reintroduces per-context + session scoping (out of scope for minimal risk).

---

## 10. Risks & mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| C3/C4 over-revoke locks a principal out | MED–HIGH | dry-run delta; scoped to managed grants (never owner grants); verify gate; exact rollback doc; test revoke on a hand-grant first |
| private→team broadening (safe agent) | LOW | safe-only tier; approved; drop team-write if stricter is wanted |
| Agent sees private in a public project (maximal memory) | LOW | publish path blocked (no write public); safe=ZDR; unsafe reading private = existing split |
| Future need for agent public-writing | — | requires per-context + session scoping (v2 path); out of scope for minimal-risk |
| Cognify OOM / stuck runner; 200-but-empty; 202 misread as done | MED | cognify ledger pins `run_in_background=False` (or polls on 202) + entity counts + 200-zero=failed + `free -h` preflight + stuck-runner check |
| Matrix drift (tiers vs. reality) | LOW | reconciliation converges to `tiers.py`; `dump_acl.py --before/--after` shows drift |
| Dead `tier_keys.*` mistaken for the model | LOW | C11 remove/reconcile |

---

## 11. Rollback plan (milestone-level)

- **M0:** revert logging + delete `dump_acl.py` + delete the plan doc (+ C11 if
  landed: restore `tier_keys.*`/test).
- **M1 (the fix):** restore `write` on `public` for `agent-provider` +
  `safe-provider` (and safe's on `private/<o>` if you dropped it) in `tiers.py`;
  re-run `bootstrap.py` (re-grants); revert the `verify.py` flips; remove the
  reconciliation step if desired. `verify.py` returns to prior green.
- **M2:** revert docs; restore `tier_keys.*` if C11 deleted them.

At every point the **live** system stays on a known-green `verify.py` state. The
fix is **C3+C4** (reconcile + matrix); they land together and revert together.

---

## Appendix A — Verified API anchors (for the implementer)

- Grant: `POST /api/v1/permissions/datasets/{principal_id}?permission_name={read|write|…}` + body `[dataset_id]`
- Revoke: `DELETE /api/v1/permissions/datasets/{principal_id}` + query
  `permission_name` + body `[dataset_id]`
- List a principal's datasets for a perm:
  `GET /api/v1/permissions/principals/{principal_id}/datasets?permission_name=…`
- List a principal's roles: `GET /api/v1/permissions/users/{user_id}/roles`
- Email → user id: `POST /api/v1/users/get-user-id` `{email}` → `{user_id}`
- Datasets (caller-visible): `GET /api/v1/datasets`
- Read gate: `POST /api/v1/search` (or `/recall`) `{query, search_type, dataset_ids}`
  (UUIDs for shared tiers; raw `add`/`search` are LLM-free)
- Write gate: `POST /api/v1/add` (files + `datasetId`) — **403 before pipeline**
- Production write: `POST /api/v1/remember` — **`add` + `cognify` + `improve`
  (LLM-bound per write)**
- Cognify: `POST /api/v1/cognify` `{dataset_ids, run_in_background}` —
  **`run_in_background=False` (default) blocks to 200; `True` returns 202 and
  must be polled via `GET /api/v1/datasets/status`**
- Server: `./run_api.sh` (uvicorn :8000) / `systemctl --user cognee-team-api.service`;
  bootstrap runs with the server **stopped** (shared SQLite ACL DB).
