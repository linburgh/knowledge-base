import unittest

from app.core.services.user import _normalize_filter
from app.schemas.user import UserCreateRequest, UserModifyRequest


class UserSchemaTest(unittest.TestCase):
    def test_create_request(self):
        request = UserCreateRequest(username="alice", display_name="Alice")

        self.assertEqual(request.username, "alice")
        self.assertEqual(request.display_name, "Alice")

    def test_modify_request_is_partial(self):
        request = UserModifyRequest(status="disabled")

        self.assertEqual(request.status, "disabled")
        self.assertIsNone(request.email)

    def test_create_request_rejects_empty_username(self):
        with self.assertRaises(ValueError):
            UserCreateRequest(username="")

    def test_empty_filter_is_treated_as_missing(self):
        self.assertIsNone(_normalize_filter(""))
        self.assertIsNone(_normalize_filter("   "))
        self.assertEqual(_normalize_filter("active"), "active")


if __name__ == "__main__":
    unittest.main()
