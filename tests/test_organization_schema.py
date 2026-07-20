import unittest

from app.schemas.knowledge_base_organization import KnowledgeBaseOrganizationBatchRequest
from app.schemas.organization import OrganizationCreateRequest, OrganizationMemberRequest


class OrganizationSchemaTest(unittest.TestCase):
    def test_create_request(self):
        request = OrganizationCreateRequest(tenant_id=1, code="head-office", name="总部")

        self.assertEqual(request.tenant_id, 1)
        self.assertEqual(request.code, "head-office")

    def test_member_request_defaults(self):
        request = OrganizationMemberRequest(user_id=1)

        self.assertEqual(request.role_code, "org_member")
        self.assertEqual(request.status, "active")

    def test_create_request_rejects_invalid_tenant(self):
        with self.assertRaises(ValueError):
            OrganizationCreateRequest(tenant_id=0, code="root", name="Root")

    def test_knowledge_base_batch_request(self):
        request = KnowledgeBaseOrganizationBatchRequest(organization_ids=[1, 2])

        self.assertEqual(request.organization_ids, [1, 2])

    def test_knowledge_base_batch_request_requires_organizations(self):
        with self.assertRaises(ValueError):
            KnowledgeBaseOrganizationBatchRequest(organization_ids=[])


if __name__ == "__main__":
    unittest.main()
