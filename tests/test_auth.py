import os
import unittest

from app.core.common.auth import hash_password, issue_token, parse_token, verify_password


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.previous_secret = os.environ.get("AUTH_SECRET")
        os.environ["AUTH_SECRET"] = "test-auth-secret"

    def tearDown(self):
        if self.previous_secret is None:
            os.environ.pop("AUTH_SECRET", None)
        else:
            os.environ["AUTH_SECRET"] = self.previous_secret

    def test_password_hash(self):
        password_hash = hash_password("ShellPass123")

        self.assertTrue(verify_password("ShellPass123", password_hash))
        self.assertFalse(verify_password("wrong-password", password_hash))

    def test_token_round_trip(self):
        token, expires_in = issue_token(42)

        self.assertEqual(expires_in, 3600)
        self.assertEqual(parse_token(token).user_id, "42")


if __name__ == "__main__":
    unittest.main()
