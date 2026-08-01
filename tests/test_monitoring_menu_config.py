from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DML = ROOT / "scripts" / "db" / "data_table_dml.sql"


def test_event_menu_is_granted_and_audit_menu_keeps_definition_without_role_relation() -> None:
    source = DML.read_text(encoding="utf-8")

    assert "('monitoring_events', '事件中心', '/monitoring/events', 6)" in source
    assert "('monitoring_audits', '审计管理', '/monitoring/audits', 8)" in source
    assert "delete from t_role_menu relation" in source
    assert "menu.code = 'monitoring_audits'" in source
    assert "menu.code <> 'monitoring_audits'" in source
    assert "menu.code not in ('monitoring_events', 'monitoring_audits')" not in source
    assert "on conflict (role_scope, role_code, menu_id) do update" in source
    assert "relation.role_code = 'p_super_admin'" in source
    assert "relation.role_code = 'tenant_admin'" in source
