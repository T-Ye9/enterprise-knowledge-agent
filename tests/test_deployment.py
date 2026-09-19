"""部署准备的确定性检查，不创建账号、不部署、不调用真实供应商。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import app
from app.deployment import cors_origins, storage_path, uploads_enabled, validate_deployment
from app.server import main, server_port


class DeploymentTests(unittest.TestCase):
    def test_upload_defaults_and_strict_environment(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
            self.assertFalse(uploads_enabled())
        with patch.dict(os.environ, {"APP_ENV": "development"}, clear=True):
            self.assertTrue(uploads_enabled())
        for key, value in [("APP_ENV", "prod-typo"), ("ALLOW_DOCUMENT_UPLOAD", "maybe")]:
            with patch.dict(os.environ, {"APP_ENV": "development", key: value}), self.assertRaises(ValueError):
                uploads_enabled()

    def test_upload_disabled_is_enforced_by_backend(self):
        with patch.dict(os.environ, {"ALLOW_DOCUMENT_UPLOAD": "false"}), TestClient(app) as http, patch("app.api.ingest_upload") as ingest:
            response = http.post("/documents", files={"file": ("test.pdf", b"%PDF-test")})
        self.assertEqual(response.status_code, 403)
        ingest.assert_not_called()

    def test_cors_production_allows_same_origin_or_exact_https(self):
        with patch.dict(os.environ, {"APP_ENV": "production", "CORS_ORIGINS": ""}):
            self.assertEqual(cors_origins(), [])
        with patch.dict(os.environ, {"APP_ENV": "production", "CORS_ORIGINS": "https://demo.example.test"}):
            self.assertEqual(cors_origins(), ["https://demo.example.test"])
        for value in ("*", "https://*.example.test", "https://demo.example.test:bad", "http://demo.example.test", "https://demo.example.test/path", "https://user:secret@example.test"):
            with self.subTest(value=value), patch.dict(os.environ, {"APP_ENV": "production", "CORS_ORIGINS": value}), self.assertRaises(ValueError):
                cors_origins()

    def test_production_startup_validates_storage_without_llm_call(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / "db")
            cache = str(Path(folder) / "cache")
            settings = {"APP_ENV": "production", "CORS_ORIGINS": "", "ALLOW_DOCUMENT_UPLOAD": "false",
                        "KNOWLEDGE_DB_PATH": db, "EMBEDDING_CACHE_DIR": cache}
            with patch.dict(os.environ, settings), patch("app.llm_client.read_configuration", return_value=("test-key", "https://example.test", "test")), patch("app.llm_client.OpenAI") as sdk:
                with TestClient(app) as http:
                    self.assertEqual(http.get("/health").status_code, 200)
            sdk.assert_not_called()
            self.assertTrue(Path(db).is_dir())
            self.assertTrue(Path(cache).is_dir())

    def test_production_missing_config_stops_startup(self):
        with patch.dict(os.environ, {"APP_ENV": "production", "CORS_ORIGINS": "", "ALLOW_DOCUMENT_UPLOAD": "false"}), patch("app.llm_client.read_configuration", side_effect=ValueError("missing key")), self.assertLogs("knowledge_agent") as logs:
            with self.assertRaises(ValueError):
                with TestClient(app):
                    pass
        self.assertIn("startup_configuration_invalid", "\n".join(logs.output))

    def test_storage_permission_failure_is_actionable_and_safe(self):
        settings = {"APP_ENV": "production", "CORS_ORIGINS": "", "ALLOW_DOCUMENT_UPLOAD": "false",
                    "KNOWLEDGE_DB_PATH": str(Path.cwd()), "EMBEDDING_CACHE_DIR": str(Path.cwd())}
        with patch.dict(os.environ, settings), patch("app.llm_client.read_configuration", return_value=("test", "https://example.test", "test")), patch("app.deployment.TemporaryFile", side_effect=PermissionError("private-secret")):
            with self.assertRaisesRegex(ValueError, "不可写") as error:
                validate_deployment()
        self.assertNotIn("private-secret", str(error.exception))

    def test_relative_production_storage_is_rejected(self):
        with patch.dict(os.environ, {"APP_ENV": "production", "CORS_ORIGINS": "", "ALLOW_DOCUMENT_UPLOAD": "false", "KNOWLEDGE_DB_PATH": "relative/db"}), patch("app.llm_client.read_configuration", return_value=("test", "https://example.test", "test")), self.assertRaisesRegex(ValueError, "绝对路径"):
            validate_deployment()

    def test_storage_path_configuration_and_defaults(self):
        with patch.dict(os.environ, {"TEST_STORAGE": "data/test-db"}):
            self.assertEqual(storage_path("TEST_STORAGE", "unused"), (Path.cwd() / "data/test-db").resolve())
        with patch.dict(os.environ, {"TEST_STORAGE": " "}), self.assertRaises(ValueError):
            storage_path("TEST_STORAGE", "unused")

    def test_platform_port_and_single_worker_command(self):
        with patch.dict(os.environ, {"PORT": "9000"}), patch("app.server.uvicorn.run") as run:
            main()
        run.assert_called_once_with("app.api:app", host="0.0.0.0", port=9000, workers=1, access_log=False)
        for value in ("no", "0", "65536"):
            with patch.dict(os.environ, {"PORT": value}), self.assertRaises(ValueError):
                server_port()

    def test_long_message_rejected_before_llm(self):
        with TestClient(app) as http, patch("app.api.create_client") as create:
            response = http.post("/chat", json={"message": "x" * 4001})
        self.assertEqual(response.status_code, 422)
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
