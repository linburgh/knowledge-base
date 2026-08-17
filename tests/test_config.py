import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertTrue(CONF.storage.minio_endpoint.startswith(("http://", "https://")))
        self.assertNotEqual(CONF.storage.minio_endpoint, "")
        self.assertEqual(CONF.storage.minio_access_key, "linburgh")
        self.assertEqual(CONF.storage.minio_secret_key, "linburgh")
        self.assertEqual(CONF.storage.minio_bucket, "knowledge-base")
        # 模型、API Key 和地址允许按部署环境配置，不固定断言某一套本地配置。
        self.assertTrue(CONF.embedding.model)
        self.assertTrue(CONF.embedding.api_key)
        self.assertTrue(CONF.embedding.base_url.startswith("http"))
        self.assertTrue(CONF.chat.model)
        self.assertTrue(CONF.chat.api_key)
        self.assertTrue(CONF.chat.base_url.startswith("http"))

    def test_config_resolves_environment_placeholders_and_types(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            (config_dir / "app.yaml").write_text(
                """
default:
  debug: ${TEST_DEBUG}
  database_url: ${TEST_DATABASE_URL}
  max_upload_size_mb: ${TEST_MAX_UPLOAD_SIZE}
  allowed_file_extensions: ${TEST_ALLOWED_EXTENSIONS}
storage:
  minio_endpoint: ${TEST_MINIO_ENDPOINT}
""",
                encoding="utf-8",
            )

            environment = {
                "OS_CONFIG_DIR": str(config_dir),
                "TEST_DEBUG": "true",
                "TEST_DATABASE_URL": "postgresql+asyncpg://user:password@postgres:5432/kb",
                "TEST_MAX_UPLOAD_SIZE": "256",
                "TEST_ALLOWED_EXTENSIONS": ".pdf,.md",
                "TEST_MINIO_ENDPOINT": "http://minio:9000",
            }
            with patch.dict(os.environ, environment, clear=False):
                configure("app")

            self.assertTrue(CONF.default.debug)
            self.assertEqual(
                CONF.default.database_url,
                "postgresql+asyncpg://user:password@postgres:5432/kb",
            )
            self.assertEqual(CONF.default.max_upload_size_mb, 256)
            self.assertEqual(CONF.default.allowed_file_extensions, [".pdf", ".md"])
            self.assertEqual(CONF.storage.minio_endpoint, "http://minio:9000")

    def test_config_reports_missing_environment_placeholder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            (config_dir / "app.yaml").write_text(
                "default:\n  database_url: ${MISSING_DATABASE_URL}\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"OS_CONFIG_DIR": str(config_dir)}, clear=False):
                with self.assertRaisesRegex(ValueError, "MISSING_DATABASE_URL"):
                    configure("app")
