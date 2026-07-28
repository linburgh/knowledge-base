import asyncio
import unittest
from datetime import UTC, datetime

from sqlalchemy.dialects import postgresql

from app.core.common.exception import BusiException
from app.core.services.organization import (
    _decode_tree_cursor,
    _encode_tree_cursor,
)
from app.db.organization import tree_children, tree_parents


class CaptureDB:
    def __init__(self):
        self.queries = []

    async def fetch_all(self, query):
        self.queries.append(query)
        return []


class OrganizationTreePaginationTest(unittest.TestCase):
    def test_cursor_round_trip_for_platform_scope(self):
        created_at = datetime(2026, 7, 28, 8, 30, tzinfo=UTC)
        cursor = _encode_tree_cursor(tenant_id=151, created_at=created_at, item_id=9)

        self.assertEqual(
            _decode_tree_cursor(cursor, includes_tenant=True),
            (151, created_at, 9),
        )

    def test_cursor_round_trip_for_tenant_scope(self):
        created_at = datetime(2026, 7, 28, 8, 30, tzinfo=UTC)
        cursor = _encode_tree_cursor(tenant_id=None, created_at=created_at, item_id=9)

        self.assertEqual(
            _decode_tree_cursor(cursor, includes_tenant=False),
            (created_at, 9),
        )

    def test_invalid_cursor_is_rejected(self):
        with self.assertRaises(BusiException):
            _decode_tree_cursor("invalid", includes_tenant=False)

    def test_parent_query_supports_tenant_cursor(self):
        db = CaptureDB()
        asyncio.run(
            tree_parents(
                db,
                tenant_id=151,
                cursor=(datetime(2026, 7, 28, tzinfo=UTC), 9),
                limit=20,
            )
        )
        sql = str(
            db.queries[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("t_organization.tenant_id = 151", sql)
        self.assertIn("t_organization.created_at >", sql)
        self.assertIn("organization_tree_child", sql)

    def test_child_query_counts_members_and_children_separately(self):
        db = CaptureDB()
        asyncio.run(tree_children(db, parent_id=1, tenant_id=151, limit=20))
        sql = str(
            db.queries[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("AS member_count", sql)
        self.assertIn("AS child_count", sql)
        self.assertIn("organization_child_descendant", sql)


if __name__ == "__main__":
    unittest.main()
