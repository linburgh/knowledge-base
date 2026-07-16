import unittest

from app.config import CONF, configure


class ConfigTest(unittest.TestCase):
    def test_default_config_has_development_sqlite(self):
        configure("app")

        self.assertEqual(CONF.default.environment, "development")
        self.assertTrue(CONF.default.database_url.startswith("sqlite+aiosqlite://"))
        self.assertEqual(CONF.default.request_id_header, "X-Request-ID")
