"""Bootstrap the cognee-team partitioning: idempotent, LLM-free, offline.

Run with the API server STOPPED (it shares the SQLite user/ACL database):

    cd cognee-team && .venv/bin/python bootstrap.py

Creates (if missing), then prints a summary:

  admin@team.local (superuser, tenant owner)
  tenant "team"
  roles  member / agent-provider
  members  (MEMBER_EMAILS)  + their private/<email> dataset
  member agents  (member_agents: each member's OWN unsafe no-ZDR providers,
                  parent = the owning member)
  datasets public (tier 1) / team (tier 2) / private/<member> (tier 3)
  ACL grants exactly as tiers.ROLE_MATRIX, granted to ROLES — never to the
  tenant principal (a tenant grant would leak to the agent members too).
  PLUS direct per-agent grants: read+write on the OWNER's private dataset
  only — so a person's own AI can work their own projects while the tier
  stays invisible to every other member, agent, and the admin.
  one "bootstrap" API key per principal -> credentials/<email>.json (chmod 600)

Re-running is safe: every step checks-then-creates; permission grants are
insert-only idempotent in cognee. API keys already labeled "bootstrap" are
reused (the raw key is only recoverable from credentials/).
"""

from __future__ import annotations

import asyncio
import json
import secrets
import stat
import sys
import uuid as uuid_mod
from pathlib import Path

from sqlalchemy import select

import cognee
from cognee.infrastructure.databases.relational import get_relational_engine
from cognee.run_migrations import run_migrations
from cognee.modules.data.methods import (
    create_authorized_dataset,
    get_authorized_dataset_by_name,
)
from cognee.modules.users.api_key.create_api_key import create_api_key
from cognee.modules.users.api_key.get_api_keys import get_api_keys
from cognee.modules.users.methods import (
    create_user,
    get_user,
    get_user_by_email,
)
from cognee.modules.users.permissions.methods import (
    give_permission_on_dataset,
)
from cognee.modules.users.roles.methods import add_user_to_role, create_role
from cognee.modules.users.tenants.methods import (
    add_user_to_tenant,
    create_tenant,
    get_tenant_roles,
    get_user_tenants,
    select_tenant,
)

sys.path.insert(0, str(Path(__file__).parent))
import tiers  # noqa: E402

HERE = Path(__file__).resolve().parent
CREDENTIALS_DIR = HERE / "credentials"
CREDENTIALS_DIR.mkdir(mode=0o700, exist_ok=True)

SEED_TEXT = {
    tiers.DATASET_PUBLIC: (
        "PUBLIC TIER SEED. This dataset is readable AND writable by unsafe AI "
        "agent providers (no zero-data-retention). Only put information here "
        "that may appear in any provider's context."
    ),
    tiers.DATASET_TEAM: (
        "TEAM TIER SEED. Internal team knowledge. Unsafe AI agent providers "
        "have no permission on this dataset; their recalls can never reach it."
    ),
}


def _save_credentials(email: str, password: str | None, api_key: str | None) -> Path:
    path = CREDENTIALS_DIR / f"{email}.json"
    payload: dict = {"email": email}
    if password:
        payload["password"] = password
    if api_key:
        payload["api_key"] = api_key
    path.write_text(json.dumps(payload, indent=2) + "\n")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    return path


async def _ensure_user(email: str, *, parent_user_id=None) -> tuple[object, bool]:
    user = await get_user_by_email(email)
    if user is not None:
        return user, False
    password = secrets.token_urlsafe(18)
    user = await create_user(
        email,
        password,
        is_superuser=False,
        is_active=True,
        is_verified=True,
        parent_user_id=parent_user_id,
    )
    _save_credentials(email, password, None)
    print(f"  created user {email}")
    return user, True


async def _existing_role_map(tenant_id, admin) -> dict[str, object]:
    """name -> Role MODEL (get_tenant_roles returns dicts; grants need models)."""
    from cognee.modules.users.models import Role

    engine = get_relational_engine()
    async with engine.get_async_session() as session:
        result = await session.execute(select(Role).where(Role.tenant_id == tenant_id))
        return {role.name: role for role in result.scalars().all()}


async def _dataset_for(user, name: str):
    ds = await get_authorized_dataset_by_name(name, user, tiers.READ)
    if ds is not None:
        return ds, False
    return await create_authorized_dataset(name, user), True


async def main(reset_keys: bool = False) -> int:
    print("== cognee-team bootstrap ==")

    # 0) migrations (idempotent — at-head is a no-op; the API server runs the
    #    same on startup, so either ordering works) -------------------------
    await run_migrations()
    print("  migrations at head")

    # 1) admin -------------------------------------------------------------
    # NB: get_user_by_email returns None (does not raise) when absent.
    admin = await get_user_by_email(tiers.ADMIN_EMAIL)
    if admin is None:
        password = secrets.token_urlsafe(24)
        admin = await create_user(
            tiers.ADMIN_EMAIL,
            password,
            is_superuser=True,
            is_active=True,
            is_verified=True,
        )
        _save_credentials(tiers.ADMIN_EMAIL, password, None)
        print(f"  created admin {tiers.ADMIN_EMAIL} (superuser)")

    # 2) tenant ------------------------------------------------------------
    # get_user_tenants returns [{"id": str, "name": str}] — coerce to UUID.
    tenant_id = None
    for t in await get_user_tenants(admin):
        if t["name"] == tiers.TENANT_NAME:
            tenant_id = uuid_mod.UUID(str(t["id"]))
    if tenant_id is None:
        tenant_id = await create_tenant(tiers.TENANT_NAME, admin.id)
        print(f"  created tenant '{tiers.TENANT_NAME}'")
    admin = await get_user(admin.id)  # refresh: active tenant now set

    # 3) roles -------------------------------------------------------------
    roles = await _existing_role_map(tenant_id, admin)
    for role_name in (tiers.MEMBER_ROLE, tiers.AGENT_ROLE):
        if role_name not in roles:
            role_id = await create_role(role_name, admin.id)
            print(f"  created role '{role_name}'")
            roles = await _existing_role_map(tenant_id, admin)

    # 4) shared datasets (owned by admin, stamped with tenant "team") -------
    datasets: dict[str, object] = {}
    for name in (tiers.DATASET_PUBLIC, tiers.DATASET_TEAM):
        ds, created = await _dataset_for(admin, name)
        datasets[name] = ds
        if created:
            print(f"  created dataset '{name}'")

    # 5) members + private datasets ----------------------------------------
    member_users: dict[str, object] = {}
    private_datasets: dict[str, object] = {}
    for email in tiers.MEMBER_EMAILS:
        user, _ = await _ensure_user(email)
        member_users[email] = user
        try:
            await add_user_to_tenant(user.id, tenant_id, admin.id)
        except Exception:
            pass  # already a member — idempotent re-run
        # add_user_to_tenant only stores MEMBERSHIP; the active tenant
        # (users.tenant_id) is what the dataset-visibility filter matches
        # against. Without it, every team-stamped dataset is dropped from
        # the user's scope. Must also happen BEFORE creating the member's
        # private dataset so it gets stamped with the tenant too.
        await select_tenant(user_id=user.id, tenant_id=tenant_id)
        user = await get_user(user.id)  # refresh active tenant
        try:
            await add_user_to_role(user.id, roles[tiers.MEMBER_ROLE].id, admin.id)
        except Exception:
            pass
        priv_name = tiers.private_dataset_name(email)
        member_users[email] = user
        ds, created = await _dataset_for(user, priv_name)
        if created:
            print(f"  created private dataset '{priv_name}' for {email}")
        private_datasets[priv_name] = ds

    # 6) member agents (unsafe providers, partitioned with their OWNER) -----
    # parent = the OWNING member: anything an agent ingests into its own
    # scratch datasets is inherited downward by that member only.
    agent_users: dict[str, object] = {}
    for agent_email, owner_email in tiers.AGENT_OWNER.items():
        owner = member_users.get(owner_email)
        if owner is None:
            raise SystemExit(
                f"agent {agent_email}: owner {owner_email} is not in member_emails"
            )
        user, _ = await _ensure_user(agent_email, parent_user_id=owner.id)
        try:
            await add_user_to_tenant(user.id, tenant_id, admin.id)
        except Exception:
            pass  # already a member — idempotent re-run
        await select_tenant(user_id=user.id, tenant_id=tenant_id)  # active tenant
        try:
            await add_user_to_role(user.id, roles[tiers.AGENT_ROLE].id, admin.id)
        except Exception:
            pass
        user = await get_user(user.id)
        agent_users[agent_email] = user
        print(f"  ensured agent provider {agent_email} (owner {owner_email})")

    # 6b) owner-private grants: each agent gets rw on ITS OWNER's private
    #     dataset — DIRECT grants (roles cannot express per-owner datasets).
    #     The negative space (no other member's private tier, no team) is
    #     what verify.py asserts.
    for agent_email, owner_email in tiers.AGENT_OWNER.items():
        priv_name = tiers.private_dataset_name(owner_email)
        for perm in (tiers.READ, tiers.WRITE):
            await give_permission_on_dataset(agent_users[agent_email], private_datasets[priv_name].id, perm)
        print(f"  granted [read, write] on '{priv_name}' to agent {agent_email}")

    # 7) ACL matrix — granted to ROLES, never to the tenant -----------------
    for role_name, dataset_perms in tiers.ROLE_MATRIX.items():
        role = roles[role_name]
        for ds_name, perms in dataset_perms.items():
            for perm in perms:
                await give_permission_on_dataset(role, datasets[ds_name].id, perm)
        print(f"  granted {dataset_perms} on role '{role_name}'")

    # 8) seed tier content (ingest only — no cognify, no LLM needed) --------
    for ds_name, text in SEED_TEXT.items():
        ds = await get_authorized_dataset_by_name(ds_name, admin, tiers.READ)
        existing = await cognee.add(text, dataset_name=ds_name, user=admin)
        print(f"  seeded '{ds_name}' (ingest-only, no graph extraction)")

    # 9) API keys ------------------------------------------------------------
    print("  API keys:")
    for email, user in {**agent_users, **member_users, tiers.ADMIN_EMAIL: admin}.items():
        keys = await get_api_keys(user)
        named = [k for k in keys if getattr(k, "name", None) == "bootstrap"]
        if named and not reset_keys:
            print(f"    {email}: bootstrap key exists -> credentials/{email}.json")
            continue
        created = await create_api_key(user, name="bootstrap")
        raw = getattr(created, "api_key", None)
        cred_path = CREDENTIALS_DIR / f"{email}.json"
        payload = json.loads(cred_path.read_text()) if cred_path.exists() else {"email": email}
        payload["api_key"] = raw
        cred_path.write_text(json.dumps(payload, indent=2) + "\n")
        cred_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        print(f"    {email}: minted key {raw[:8]}**** -> credentials/{email}.json")

    print("== bootstrap complete ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(reset_keys="--reset-keys" in sys.argv)))
