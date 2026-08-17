import asyncio
import unittest
from datetime import UTC, datetime

from app.core.common.exception import BusiException
from app.core.common.log_utils import trace
from app.core.common.utils import mask_sensitive, normalize_space, to_china_standard_time


class CommonTest(unittest.TestCase):
    def test_busi_exception(self):
        exc = BusiException("invalid", status_code=422)

        self.assertEqual(exc.message, "invalid")
        self.assertEqual(exc.status_code, 422)

    def test_utils(self):
        self.assertEqual(normalize_space("a  \n b"), "a b")
        self.assertEqual(mask_sensitive("1234567890"), "1234****7890")
        converted = to_china_standard_time(datetime(2026, 8, 8, 23, 30, tzinfo=UTC))
        self.assertEqual(converted.isoformat(), "2026-08-09T07:30:00+08:00")
        with self.assertRaisesRegex(ValueError, "Timezone-aware"):
            to_china_standard_time(datetime(2026, 8, 9, 7, 30))

    def test_trace_preserves_sync_exception(self):
        @trace
        def fail():
            raise BusiException("invalid")

        with self.assertRaisesRegex(BusiException, "invalid"):
            fail()

    def test_trace_preserves_async_exception(self):
        async def fail_impl():
            raise BusiException("invalid")

        fail = trace(fail_impl)

        async def run():
            with self.assertRaisesRegex(BusiException, "invalid"):
                await fail()

        asyncio.run(run())
