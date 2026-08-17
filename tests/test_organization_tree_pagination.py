import asyncio
import unittest
from datetime import UTC, datetime

from sqlalchemy.dialects import postgresql

from app.core.common.exception import BusiException
from app.core.services.platform.organization import (
    _decode_tree_cursor,
    _encode_tree_cursor,
)
from app.db.platform.organization import (
    locate_search,
    organization_member_counts,
    tree_children,
    tree_parent_has_children,
    tree_parents,
)


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
        self.assertNotIn("organization_tree_child", sql)
        self.assertNotIn("GROUP BY", sql)

    def test_parent_has_children_query_is_scoped_to_current_page(self):
        db = CaptureDB()
        asyncio.run(
            tree_parent_has_children(
                db,
                parent_ids=[11, 12, 13],
                tenant_id=151,
            )
        )
        sql = str(
            db.queries[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("tree_parent.id IN (11, 12, 13)", sql)
        self.assertIn("tree_parent.tenant_id = 151", sql)
        self.assertIn("EXISTS", sql)
        self.assertNotIn("GROUP BY", sql)

    def test_child_query_pages_before_child_count_statistics(self):
        db = CaptureDB()
        asyncio.run(tree_children(db, parent_id=1, tenant_id=151, limit=20))
        sql = str(
            db.queries[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertNotIn("member_count", sql)
        self.assertNotIn("AS child_count", sql)
        self.assertNotIn("organization_child_descendant", sql)
        self.assertNotIn("GROUP BY", sql)
        self.assertIn("LIMIT 21", sql)

    def test_member_count_query_is_scoped_to_current_page(self):
        db = CaptureDB()
        asyncio.run(organization_member_counts(db, organization_ids=[11, 12, 13]))
        sql = str(
            db.queries[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("t_organization_member.organization_id IN (11, 12, 13)", sql)
        self.assertIn("GROUP BY t_organization_member.organization_id", sql)

    def test_locate_search_is_scoped_and_matches_name_or_code(self):
        db = CaptureDB()
        asyncio.run(locate_search(db, tenant_id=151, keyword="节点", limit=20))
        sql = str(
            db.queries[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("t_organization.tenant_id = 151", sql)
        self.assertIn("t_organization.name ILIKE", sql)
        self.assertIn("t_organization.code ILIKE", sql)
        self.assertIn("LIMIT 20", sql)


if __name__ == "__main__":
    unittest.main()
