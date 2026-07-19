import unittest
from datetime import UTC, datetime

from app.core.common.exception import BusiException
from app.core.services.platform_overview import _resolve_range


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


if __name__ == "__main__":
    unittest.main()
