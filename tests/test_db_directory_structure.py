from __future__ import annotations

import importlib
import unittest
from pathlib import Path

DB_ROOT = Path(__file__).parents[1] / "app" / "db"

ROOT_MODULES = {"api", "base", "models", "vector_store"}

EXPECTED_MODULES = {
    "platform": {
        "audit_log",
        "auth_session",
        "evaluation_case_result",
        "evaluation_optimization",
        "evaluation_run",
        "evaluation_task",
        "login_log",
        "organization",
        "overview",
        "platform_role",
        "system_menu",
        "system_menu_action",
        "tenant",
        "tenant_member",
        "user",
    },
    "knowledge_base": {
        "conversation",
        "conversation_message",
        "document",
        "document_chunk",
        "indexing_task",
        "index_version",
        "mgr",
        "message_citation",
        "organization",
        "overview",
        "prompt",
        "qa_config",
        "user",
    },
    "monitoring": {
        "alert",
        "alert_evidence",
        "event",
        "gather_action",
        "gather_target",
        "metric_definition",
        "metric_rule",
        "metric_value",
        "notification_channel",
        "notification_policy",
        "notification_policy_channel",
        "notification_record",
        "state_snapshot",
    },
}


class DbDirectoryStructureTest(unittest.TestCase):
    def test_root_only_contains_database_infrastructure(self) -> None:
        actual_modules = {
            path.stem for path in DB_ROOT.glob("*.py") if path.name != "__init__.py"
        }

        self.assertEqual(actual_modules, ROOT_MODULES)

    def test_repository_modules_are_grouped_by_business_domain(self) -> None:
        for package, expected_modules in EXPECTED_MODULES.items():
            package_root = DB_ROOT / package
            actual_modules = {
                path.stem
                for path in package_root.glob("*.py")
                if path.name != "__init__.py"
            }

            self.assertEqual(actual_modules, expected_modules)

    def test_all_grouped_repository_modules_can_be_imported(self) -> None:
        for package, modules in EXPECTED_MODULES.items():
            for module in modules:
                with self.subTest(package=package, module=module):
                    importlib.import_module(f"app.db.{package}.{module}")


if __name__ == "__main__":
    unittest.main()
