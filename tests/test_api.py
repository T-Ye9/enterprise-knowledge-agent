"""HTTP 数据结构、Agent 委托和错误状态测试，不请求真实模型。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock, patch

from fastapi.testclient import TestClient
from openai import APITimeoutError, APIConnectionError
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent import AgentLimitError
from app.api import app


class APITests(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(app)

    def tearDown(self):
        self.http.close()

    def test_health_without_llm(self):
        with patch("app.api.create_client") as create:
            result = self.http.get("/health")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"status": "ok"})
        create.assert_not_called()

    def test_chat_delegates_to_agent_and_preserves_trace(self):
        client = Mock()
        trace = {"final_answer": "56088", "path": ["START", "agent", "tools", "agent", "END"], "tool_calls": [{"name": "calculator", "result": {"result": 56088}}], "llm_calls": 2}
        with patch("app.api.create_client", return_value=(client, "test")), patch("app.api.run_agent", return_value=trace) as run:
            response = self.http.post("/chat", json={"message": "  123 * 456  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "56088")
        self.assertEqual(response.json()["path"], trace["path"])
        self.assertEqual(response.json()["tool_calls"], trace["tool_calls"])
        run.assert_called_once_with(client, "test", "123 * 456", session_id=response.json()["session_id"], checkpointer=ANY)
        client.close.assert_called_once()

    def test_invalid_message(self):
        with patch("app.api.create_client") as create:
            for body in ({}, {"message": " "}, {"message": 123}, {"message": None}):
                with self.subTest(body=body):
                    self.assertEqual(self.http.post("/chat", json=body).status_code, 422)
        create.assert_not_called()

    def test_missing_configuration(self):
        with patch("app.api.create_client", side_effect=ValueError("private configuration")):
            result = self.http.post("/chat", json={"message": "hi"})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private configuration", result.text)

    def test_agent_and_upstream_errors_close_client(self):
        for error, status in [
            (AgentLimitError("loop"), 508), (ValueError("private error"), 502),
            (APITimeoutError(request=httpx.Request("POST", "https://example.test")), 504),
            (APIConnectionError(request=httpx.Request("POST", "https://example.test")), 502),
        ]:
            with self.subTest(status=status):
                client = Mock()
                with patch("app.api.create_client", return_value=(client, "test")), patch("app.api.run_agent", side_effect=error):
                    response = self.http.post("/chat", json={"message": "hi"})
                self.assertEqual(response.status_code, status)
                self.assertNotIn("private error", response.text)
                client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
