from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = (ROOT / "scripts/db/default_acc_dml.sql").read_text(encoding="utf-8")


def test_seed_contains_all_documented_test_accounts() -> None:
    usernames = {
        "linburgh",
        "tenant-admin-acc",
        "zhangfei",
        "zhugeliang",
        "guest",
        "multi-tenant",
        "single-tenant",
    }

    assert SEED.count("example.test") == len(usernames)
    for username in usernames:
        assert f"'{username}'" in SEED


def test_seed_injects_password_hashes_instead_of_storing_credentials() -> None:
    password_variables = {
        "linburgh_password_hash",
        "tenant_admin_acc_password_hash",
        "zhangfei_password_hash",
        "zhugeliang_password_hash",
        "guest_password_hash",
        "multi_tenant_password_hash",
        "single_tenant_password_hash",
    }

    for variable in password_variables:
        assert f":'{variable}'" in SEED
        assert f":{{?{variable}}}" in SEED
    assert "linburgh/linburgh" not in SEED
    assert "guest / guest" not in SEED


def test_seed_uses_configured_tenant_and_organization_roles() -> None:
    assert "'tenant_admin'" in SEED
    assert "'tenant_member'" in SEED
    assert "'tenant_guest'" in SEED
    assert "'org_admin'" in SEED
    assert "'org_member'" in SEED
    assert "'tenant_owner'" not in SEED


def test_seed_is_idempotent_for_business_keys() -> None:
    assert "on conflict (username) do update" in SEED
    assert SEED.count("on conflict (code) do update") == 4
    assert "on conflict (tenant_id, user_id) do update" in SEED
    assert "on conflict (organization_id, user_id) do update" in SEED
    assert "on conflict (user_id, role_id) do nothing" in SEED
