import unittest

from app.core.common.roles import effective_role, is_platform_super_admin
from app.core.services.platform.permission import _role_pairs as permission_role_pairs
from app.core.services.platform.system_menu import _role_pairs as menu_role_pairs


class EffectiveRoleTest(unittest.TestCase):
    def test_platform_super_admin_overrides_tenant_admin(self):
        context = {
            "platform_roles": [{"code": "p_super_admin", "status": "active"}],
            "tenant_role": "tenant_admin",
            "organizations": [{"role_code": "org_admin"}],
        }

        self.assertEqual(effective_role(context), "p_super_admin")
        self.assertTrue(is_platform_super_admin(context))
        self.assertEqual(menu_role_pairs(context), [("platform", "p_super_admin")])
        self.assertEqual(permission_role_pairs(context), [("platform", "p_super_admin")])

    def test_tenant_admin_overrides_lower_scope_roles(self):
        context = {
            "platform_roles": [],
            "tenant_role": "tenant_admin",
            "organizations": [{"role_code": "org_admin"}],
        }

        self.assertEqual(effective_role(context), "tenant_admin")
        self.assertFalse(is_platform_super_admin(context))

    def test_inactive_platform_super_admin_does_not_override_active_tenant_role(self):
        context = {
            "platform_roles": [{"code": "p_super_admin", "status": "disabled"}],
            "tenant_role": "tenant_admin",
        }

        self.assertEqual(effective_role(context), "tenant_admin")


if __name__ == "__main__":
    unittest.main()
