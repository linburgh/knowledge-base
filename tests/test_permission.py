import unittest
from unittest.mock import AsyncMock, patch

from app.core.common.auth import CurrentUser
from app.core.common.exception import BusiException
from app.core.common.permission import require_action


class PermissionDecoratorTest(unittest.IsolatedAsyncioTestCase):
    async def test_require_action_checks_before_service_method(self):
        calls: list[str] = []

        @require_action("knowledge_base:create")
        async def create(current_user: CurrentUser):
            calls.append("service")
            return "created"

        current_user = CurrentUser(user_id="1")
        with patch(
            "app.core.services.permission.require_action",
            new=AsyncMock(),
        ) as permission_check:
            result = await create(current_user=current_user)

        self.assertEqual(result, "created")
        self.assertEqual(calls, ["service"])
        permission_check.assert_awaited_once_with(current_user, "knowledge_base:create")

    async def test_require_action_rejects_missing_context(self):
        @require_action("knowledge_base:create")
        async def create(current_user: CurrentUser):
            return "created"

        with self.assertRaises(BusiException) as context:
            await create()

        self.assertEqual(context.exception.status_code, 401)

    def test_require_action_rejects_empty_code(self):
        with self.assertRaises(ValueError):
            require_action(" ")


if __name__ == "__main__":
    unittest.main()
