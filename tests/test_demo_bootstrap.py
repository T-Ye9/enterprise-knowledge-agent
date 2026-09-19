"""启动入库开关、真实 ingestion 委托和失败关闭测试。"""
import os
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api import app
from app.demo_bootstrap import bootstrap_demo


class DemoBootstrapTests(unittest.TestCase):
    def test_disabled_does_not_load_model(self):
        with patch.dict(os.environ, {"BOOTSTRAP_DEMO_KNOWLEDGE_BASE": "false"}), patch("app.embeddings.Embedder") as model:
            bootstrap_demo()
        model.assert_not_called()

    def test_only_public_documents_reuse_index_and_close_store(self):
        store = Mock()
        with patch.dict(os.environ, {"BOOTSTRAP_DEMO_KNOWLEDGE_BASE": "true"}), patch("app.embeddings.Embedder"), patch("app.vector_store.VectorStore", return_value=store), patch("app.knowledge_base.index_pdf") as index:
            bootstrap_demo()
        self.assertEqual([call.args[0].name for call in index.call_args_list],
                         ["demo-company-policy.pdf", "web-demo-policy.pdf"])
        store.close.assert_called_once()

    def test_initialization_error_stops_service_and_closes_store(self):
        store = Mock()
        with patch.dict(os.environ, {"BOOTSTRAP_DEMO_KNOWLEDGE_BASE": "true"}), patch("app.embeddings.Embedder"), patch("app.vector_store.VectorStore", return_value=store), patch("app.knowledge_base.index_pdf", side_effect=RuntimeError("fixture failure")), self.assertLogs("knowledge_agent") as logs:
            with self.assertRaises(RuntimeError):
                with TestClient(app):
                    pass
        store.close.assert_called_once()
        self.assertIn("startup_configuration_invalid", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
