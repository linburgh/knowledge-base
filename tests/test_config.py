import os
import unittest
from pathlib import Path

from app.config import CONF, configure


class ConfigTest(unittest.TestCase):
    def test_default_config_has_development_postgresql_and_minio(self):
        os.environ["OS_CONFIG_DIR"] = str(Path.cwd() / "etc")
        configure("app")

        self.assertEqual(CONF.default.environment, "development")
        self.assertTrue(CONF.default.database_url.startswith("postgresql+asyncpg://"))
        self.assertEqual(CONF.default.request_id_header, "X-Request-ID")
        self.assertEqual(CONF.default.max_upload_size_mb, 100)
        self.assertEqual(CONF.storage.backend, "minio")
        self.assertEqual(CONF.storage.minio_endpoint, "http://127.0.0.1:9000")
        self.assertEqual(CONF.storage.minio_access_key, "linburgh")
        self.assertEqual(CONF.storage.minio_secret_key, "linburgh")
        self.assertEqual(CONF.storage.minio_bucket, "knowledge-base")
