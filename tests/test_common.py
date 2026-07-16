import unittest

from app.core.common.exception import BusiException
from app.core.common.utils import mask_sensitive, normalize_space


class CommonTest(unittest.TestCase):
    def test_busi_exception(self):
        exc = BusiException("invalid", status_code=422)

        self.assertEqual(exc.message, "invalid")
        self.assertEqual(exc.status_code, 422)

    def test_utils(self):
        self.assertEqual(normalize_space("a  \n b"), "a b")
        self.assertEqual(mask_sensitive("1234567890"), "1234****7890")
