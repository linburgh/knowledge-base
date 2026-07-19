import unittest

from app.core.common.utils import normalize_optional_filter
from app.schemas.tenant import TenantCreateRequest, TenantModifyRequest


class TenantSchemaTest(unittest.TestCase):
    def test_create_request(self):
        request = TenantCreateRequest(code="acme", name="Acme")

        self.assertEqual(request.code, "acme")
        self.assertEqual(request.name, "Acme")

    def test_modify_request_allows_partial_update(self):
        request = TenantModifyRequest(status="disabled")

        self.assertEqual(request.status, "disabled")
        self.assertIsNone(request.name)

    def test_create_request_rejects_empty_required_fields(self):
        with self.assertRaises(ValueError):
            TenantCreateRequest(code="", name="Acme")

    def test_empty_filter_is_treated_as_missing(self):
        self.assertIsNone(normalize_optional_filter(""))
        self.assertIsNone(normalize_optional_filter("   "))
        self.assertEqual(normalize_optional_filter("active"), "active")


if __name__ == "__main__":
    unittest.main()
