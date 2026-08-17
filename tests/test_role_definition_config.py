from __future__ import annotations

from pathlib import Path

from app.db.models import OrganizationRole, TenantRole

ROOT = Path(__file__).resolve().parents[1]
DDL = (ROOT / "scripts/db/data_table_ddl.sql").read_text(encoding="utf-8")
DML = (ROOT / "scripts/db/data_table_dml.sql").read_text(encoding="utf-8")


def test_tenant_and_organization_role_models_define_stable_catalog_fields() -> None:
    expected_columns = {
        "id",
        "code",
        "name",
        "description",
        "status",
        "sort_order",
        "created_at",
        "updated_at",
    }

    assert set(TenantRole.c.keys()) == expected_columns
    assert set(OrganizationRole.c.keys()) == expected_columns
    assert TenantRole.c.id.primary_key
    assert OrganizationRole.c.id.primary_key
    assert TenantRole.c.id.identity is not None
    assert OrganizationRole.c.id.identity is not None


def test_role_catalog_models_declare_named_unique_code_indexes() -> None:
    tenant_indexes = {index.name: index for index in TenantRole.indexes}
    organization_indexes = {index.name: index for index in OrganizationRole.indexes}

    assert tenant_indexes["u_idx_t_tenant_role_code"].unique
    assert organization_indexes["u_idx_t_organization_role_code"].unique
    assert "idx_t_tenant_role_status_sort" in tenant_indexes
    assert "idx_t_organization_role_status_sort" in organization_indexes


def test_role_catalog_ddl_follows_database_constraints() -> None:
    assert "create table if not exists t_tenant_role" in DDL
    assert "create table if not exists t_organization_role" in DDL
    assert "u_idx_t_tenant_role_code" in DDL
    assert "u_idx_t_organization_role_code" in DDL

    tenant_block = DDL.split("create table if not exists t_tenant_role", 1)[1].split(");", 1)[0]
    organization_block = DDL.split("create table if not exists t_organization_role", 1)[1].split(
        ");", 1
    )[0]
    assert "foreign key" not in tenant_block.lower()
    assert "foreign key" not in organization_block.lower()
    assert "check" not in tenant_block.lower()
    assert "check" not in organization_block.lower()


def test_role_catalog_dml_initializes_only_confirmed_fixed_roles() -> None:
    assert "insert into t_tenant_role" in DML
    assert "('tenant_admin', '租户管理员'" in DML
    assert "('tenant_member', '租户成员'" in DML
    assert "('tenant_guest', '租户访客'" in DML
    assert "insert into t_organization_role" in DML
    assert "('org_admin', '组织管理员'" in DML
    assert "('org_member', '组织成员'" in DML
    assert DML.count("on conflict (code) do update") >= 3
    role_catalog_dml = DML.split("insert into t_tenant_role", 1)[1].split(
        "insert into t_system_menu", 1
    )[0]
    assert "tenant_owner" not in role_catalog_dml
