import unittest
import asyncio
from datetime import UTC, datetime

from sqlalchemy.dialects import postgresql

from app.core.common.exception import BusiException
from app.db.platform_overview import NON_BUSINESS_ACTIVITY_ACTIONS, recent_activities
from app.core.services.platform_overview import _resolve_range


class CaptureDB:
    def __init__(self):
        self.query = None

    async def fetch_all(self, query):
        self.query = query
        return []


class PlatformOverviewServiceTest(unittest.TestCase):
    def test_default_range(self):
        start_at, end_at = _resolve_range("7d", None, None)

        self.assertEqual((end_at - start_at).days, 7)
        self.assertIsNotNone(start_at.tzinfo)
        self.assertIsNotNone(end_at.tzinfo)

    def test_custom_range_requires_both_times(self):
        with self.assertRaises(BusiException):
            _resolve_range("custom", None, None)

    def test_custom_range_rejects_reverse_times(self):
        start_at = datetime(2026, 7, 20, tzinfo=UTC)
        end_at = datetime(2026, 7, 19, tzinfo=UTC)

        with self.assertRaises(BusiException):
            _resolve_range("custom", start_at, end_at)

    def test_invalid_range_is_rejected(self):
        with self.assertRaises(BusiException):
            _resolve_range("365d", None, None)

    def test_recent_activities_excludes_authentication_events_for_platform_scope(self):
        db = CaptureDB()
        asyncio.run(recent_activities(db))

        sql = str(
            db.query.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for action in NON_BUSINESS_ACTIVITY_ACTIONS:
            self.assertIn(action, sql)
        self.assertNotIn("t_tenant_member", sql)

    def test_recent_activities_uses_target_tenant_for_tenant_scope(self):
        db = CaptureDB()
        asyncio.run(recent_activities(db, tenant_id=151))

        sql = str(
            db.query.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("t_tenant_member.tenant_id = 151", sql)
        self.assertIn("t_knowledge_base.tenant_id = 151", sql)
        self.assertNotIn("t_audit_log.actor_id =", sql)


if __name__ == "__main__":
    unittest.main()
