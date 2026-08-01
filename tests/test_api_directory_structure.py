from __future__ import annotations

import importlib
import unittest
from pathlib import Path

from fastapi import FastAPI

from app.api.v1 import api_router

API_ROOT = Path(__file__).parents[1] / "app" / "api" / "v1"

EXPECTED_MODULES = {
    "knowledge_base": {"mgr", "overview", "qa_config"},
    "platform": {"overview", "roles"},
}

REMOVED_ROOT_MODULES = {
    "knowledge_bases",
    "knowledge_base_overview",
    "knowledge_base_qa_config",
    "platform_overview",
    "platform_roles",
}

EXPECTED_ROUTES = {
    "/knowledge-bases": {"KnowledgeBase"},
    "/knowledge-bases/{kb_id}/overview": {"KnowledgeBase"},
    "/knowledge-bases/{kb_id}/qa-config": {"KnowledgeBaseQaConfig"},
    "/platform/overview": {"Platform"},
    "/platform/roles": {"PlatformRole"},
    "/platform/users/{user_id}/roles": {"PlatformRole"},
}


class ApiDirectoryStructureTest(unittest.TestCase):
    def test_removed_api_modules_are_not_flattened_at_root(self) -> None:
        root_modules = {path.stem for path in API_ROOT.glob("*.py")}

        self.assertTrue(REMOVED_ROOT_MODULES.isdisjoint(root_modules))

    def test_api_modules_are_grouped_by_route_domain(self) -> None:
        for package, expected_modules in EXPECTED_MODULES.items():
            package_root = API_ROOT / package
            actual_modules = {
                path.stem
                for path in package_root.glob("*.py")
                if path.name != "__init__.py"
            }

            self.assertEqual(actual_modules, expected_modules)

    def test_all_grouped_api_modules_can_be_imported(self) -> None:
        for package, modules in EXPECTED_MODULES.items():
            for module in modules:
                with self.subTest(package=package, module=module):
                    importlib.import_module(f"app.api.v1.{package}.{module}")

    def test_route_paths_and_openapi_tags_are_unchanged(self) -> None:
        application = FastAPI()
        application.include_router(api_router)
        paths = application.openapi()["paths"]

        for path, expected_tags in EXPECTED_ROUTES.items():
            with self.subTest(path=path):
                self.assertIn(path, paths)
                actual_tags = {
                    tag
                    for operation in paths[path].values()
                    for tag in operation.get("tags", [])
                }
                self.assertEqual(actual_tags, expected_tags)


if __name__ == "__main__":
    unittest.main()
