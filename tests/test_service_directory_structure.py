from __future__ import annotations

import importlib
import unittest
from pathlib import Path

SERVICE_ROOT = Path(__file__).parents[1] / "app" / "core" / "services"

EXPECTED_MODULES = {
    "platform": {
        "audit",
        "authentication",
        "evaluation",
        "evaluation_access",
        "organization",
        "permission",
        "overview",
        "platform_role",
        "system_menu",
        "tenant",
        "tenant_member",
        "tenant_resource",
        "user",
    },
    "knowledge_base": {
        "chat",
        "conversation",
        "document",
        "guest",
        "ingestion",
        "mgr",
        "overview",
        "qa_config",
        "retrieval",
    },
    "monitoring": {
        "access",
        "analysis",
        "analysis_tools",
        "mgr",
        "rule",
    },
}


class ServiceDirectoryStructureTest(unittest.TestCase):
    def test_business_services_are_not_flattened_at_root(self) -> None:
        root_modules = {
            path.stem
            for path in SERVICE_ROOT.glob("*.py")
            if path.name != "__init__.py"
        }

        self.assertEqual(root_modules, set())

    def test_service_modules_are_grouped_by_business_domain(self) -> None:
        for package, expected_modules in EXPECTED_MODULES.items():
            package_root = SERVICE_ROOT / package
            actual_modules = {
                path.stem
                for path in package_root.glob("*.py")
                if path.name != "__init__.py"
            }

            self.assertEqual(actual_modules, expected_modules)

    def test_all_grouped_service_modules_can_be_imported(self) -> None:
        for package, modules in EXPECTED_MODULES.items():
            for module in modules:
                with self.subTest(package=package, module=module):
                    importlib.import_module(
                        f"app.core.services.{package}.{module}"
                    )


if __name__ == "__main__":
    unittest.main()
