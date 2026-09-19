"""故障注入测试：真实 HTTP/Agent，模拟外部故障，不使用真实密钥。"""
import io
import json
import os
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from openai import APIConnectionError, APITimeoutError

from app.api import app
from app.agent import AgentLimitError, run_agent
from app.document_processing import DocumentError
from app.document_upload import InvalidDocument, ingest_upload
from app.llm_client import create_client
from app.reliability import log_event
from app.tool_runtime import execute_tool
from test_agent import response, tool
from test_document_upload import pdf_bytes
from test_streaming import parse_sse


SECRET = "private-marker-never-log"


class ReliabilityTests(unittest.TestCase):
    def test_log_whitelist_drops_payloads_and_exception_text(self):
        with self.assertLogs("knowledge_agent", level="INFO") as logs:
            log_event("failure", error=RuntimeError(SECRET), api_key=SECRET,
                      document=SECRET, arguments=SECRET, status=503)
        text = "\n".join(logs.output)
        self.assertNotIn(SECRET, text)
        self.assertIn("RuntimeError", text)
        self.assertIn("503", text)

    def test_agent_stdout_and_logs_do_not_include_business_content(self):
        client = Mock()
        client.chat.completions.create.side_effect = [
            response(calls=[tool("search_knowledge_base", json.dumps({"query": SECRET}))]),
            response("知识库中没有足够依据回答这个问题。")]
        output = io.StringIO()
        with patch("sys.stdout", output), patch("app.tool_runtime.search_knowledge_base", return_value={"results": [{"text": SECRET}]}), self.assertLogs("knowledge_agent") as logs:
            run_agent(client, "test", SECRET)
        self.assertNotIn(SECRET, output.getvalue() + "\n".join(logs.output))

    def test_environment_invalid_before_sdk_creation(self):
        invalid = [{"DEEPSEEK_API_KEY": ""}, {"DEEPSEEK_MODEL": " "},
                   {"DEEPSEEK_BASE_URL": "not-a-url"},
                   {"DEEPSEEK_BASE_URL": "https://user:password@example.test"},
                   {"DEEPSEEK_BASE_URL": "https://example.test?key=secret"}]
        for values in invalid:
            with self.subTest(values=values), patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key", "DEEPSEEK_MODEL": "test", "DEEPSEEK_BASE_URL": "https://example.test", **values}), patch("app.llm_client.load_dotenv"), patch("app.llm_client.OpenAI") as sdk:
                with self.assertRaises(ValueError):
                    create_client()
                sdk.assert_not_called()

    def test_sdk_timeout_and_retry_policy(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key", "DEEPSEEK_MODEL": "test", "DEEPSEEK_BASE_URL": "https://example.test"}), patch("app.llm_client.load_dotenv"), patch("app.llm_client.OpenAI") as sdk:
            create_client()
        self.assertEqual(sdk.call_args.kwargs["timeout"], 60.0)
        self.assertEqual(sdk.call_args.kwargs["max_retries"], 0)

    def test_http_and_sse_same_safe_error_status_and_release_resources(self):
        request = httpx.Request("POST", "https://example.test")
        failures = [(APITimeoutError(request=request), 504),
                    (APIConnectionError(request=request, message=SECRET), 502),
                    (AgentLimitError(SECRET), 508), (RuntimeError(SECRET), 502),
                    (KeyError(SECRET), 500)]
        for error, status in failures:
            with self.subTest(error=type(error).__name__), TestClient(app) as http:
                client = Mock()
                with patch("app.api.create_client", return_value=(client, "test")), patch("app.api.run_agent", side_effect=error), self.assertLogs("knowledge_agent") as logs:
                    result = http.post("/chat", json={"message": SECRET})
                self.assertEqual(result.status_code, status)
                self.assertNotIn(SECRET, result.text + "\n".join(logs.output))
                client.close.assert_called_once()
                client.reset_mock()
                with patch("app.chat_stream.create_client", return_value=(client, "test")), patch("app.chat_stream.run_agent", side_effect=error), self.assertLogs("knowledge_agent"):
                    streamed = http.post("/chat/stream", json={"message": SECRET})
                records = parse_sse(streamed.text)
                self.assertEqual(records[-1]["event"], "error")
                self.assertEqual(records[-1]["data"]["status"], status)
                self.assertNotIn(SECRET, streamed.text)
                self.assertNotIn("done", [item["event"] for item in records])
                client.close.assert_called_once()
                self.assertEqual(http.get("/health").status_code, 200)

    def test_validation_does_not_echo_input(self):
        with TestClient(app) as http:
            response = http.post("/chat", json={"message": {"private": SECRET}})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(SECRET, response.text)

    def test_cleanup_failure_preserves_timeout_and_stream_terminal_event(self):
        client = Mock()
        client.close.side_effect = RuntimeError(SECRET)
        error = APITimeoutError(request=httpx.Request("POST", "https://example.test"))
        with TestClient(app) as http, self.assertLogs("knowledge_agent") as logs:
            with patch("app.api.create_client", return_value=(client, "test")), patch("app.api.run_agent", side_effect=error):
                result = http.post("/chat", json={"message": "test"})
            with patch("app.chat_stream.create_client", return_value=(client, "test")), patch("app.chat_stream.run_agent", side_effect=error):
                streamed = http.post("/chat/stream", json={"message": "test"})
            self.assertEqual(http.get("/health").status_code, 200)
        self.assertEqual(result.status_code, 504)
        self.assertEqual(parse_sse(streamed.text)[-1]["data"]["status"], 504)
        self.assertEqual(client.close.call_count, 2)
        self.assertIn("client_cleanup_failed", "\n".join(logs.output))
        self.assertNotIn(SECRET, "\n".join(logs.output))

    def test_invalid_arguments_and_unknown_tool_are_safe(self):
        with self.assertLogs("knowledge_agent") as logs:
            for name, args in [(SECRET, "{}"), ("calculator", SECRET), ("calculator", "[]"),
                               ("calculator", '{"a":1,"b":0,"operation":"divide"}'),
                               ("search_knowledge_base", '{"query":"x","top_k":true}')]:
                self.assertIn("error", execute_tool(name, args))
        self.assertNotIn(SECRET, "\n".join(logs.output))

    def test_vector_failure_returned_as_tool_error_then_sent_to_llm(self):
        client = Mock()
        client.chat.completions.create.side_effect = [response(calls=[tool("search_knowledge_base", '{"query":"制度"}')]), response("检索服务失败，请稍后重试。")]
        with patch("app.tool_runtime.search_knowledge_base", side_effect=RuntimeError(SECRET)), self.assertLogs("knowledge_agent") as logs:
            trace = run_agent(client, "test", "制度")
        result = trace["tool_calls"][0]["result"]
        self.assertIn("error", result)
        self.assertNotIn(SECRET, json.dumps(result) + "\n".join(logs.output))
        sent = client.chat.completions.create.call_args.kwargs["messages"][-1]
        self.assertEqual(json.loads(sent["content"]), result)

    def test_upload_empty_pdf_and_database_failure_are_distinct(self):
        store = Mock()
        with patch("app.embeddings.Embedder"), patch("app.vector_store.VectorStore", return_value=store), TestClient(app) as http:
            # 真实解析空白页并拒绝，不写入数据库。
            blank = http.post("/documents", files={"file": ("blank.pdf", pdf_bytes())})
            self.assertEqual(blank.status_code, 400)
            store.save_chunks.assert_not_called()
            store.close.assert_called_once()
            with patch("app.knowledge_base.index_pdf", side_effect=ValueError(SECRET)):
                failed = http.post("/documents", files={"file": ("test.pdf", pdf_bytes())})
            self.assertEqual(failed.status_code, 503)
            self.assertNotIn(SECRET, failed.text)

    def test_corrupt_and_unsupported_pdf_rejected(self):
        with TestClient(app) as http, patch("app.embeddings.Embedder") as embedder:
            for name, body in [("test.txt", b"text"), ("broken.pdf", b"%PDF-broken"), ("empty.pdf", b"")]:
                with self.subTest(name=name):
                    self.assertEqual(http.post("/documents", files={"file": (name, body)}).status_code, 400)
        embedder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
