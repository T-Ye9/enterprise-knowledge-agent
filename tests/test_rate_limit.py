"""公开聊天入口共用生产限流；拒绝请求不会调用模型或开始 SSE。"""
import os
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api import CHAT_RATE_LOCK, CHAT_REQUEST_TIMES, app
from app.conversation_memory import ConversationMemory


async def fake_stream(*args):
    yield 'event: done\ndata: {"answer":"ok","session_id":"00000000-0000-0000-0000-000000000001","sources":[]}\n\n'


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        with CHAT_RATE_LOCK:
            CHAT_REQUEST_TIMES.clear()

    def tearDown(self):
        with CHAT_RATE_LOCK:
            CHAT_REQUEST_TIMES.clear()

    def test_chat_and_stream_share_limit_and_recover_after_window(self):
        trace = {"final_answer": "ok", "path": ["START", "agent", "END"],
                 "tool_calls": [], "llm_calls": 1}
        with (patch.dict(os.environ, {"APP_ENV": "production"}),
              patch("app.api.monotonic", return_value=100.0) as clock,
              patch("app.api.create_client", return_value=(Mock(), "test")) as create,
              patch("app.api.run_agent", return_value=trace),
              patch("app.api.stream_chat", side_effect=fake_stream) as stream,
              patch("app.api.validate_deployment"),
              patch("app.api.bootstrap_demo"),
              patch("app.api.MEMORY", ConversationMemory())):
            with TestClient(app) as http:
                for _ in range(9):
                    self.assertEqual(http.post("/chat", json={"message": "hello"}).status_code, 200)
                self.assertEqual(http.post("/chat/stream", json={"message": "hello"}).status_code, 200)
                self.assertEqual(http.get("/health").status_code, 200)
                for path in ("/chat", "/chat/stream"):
                    denied = http.post(path, json={"message": "hello"},
                                       headers={"X-Forwarded-For": "203.0.113.42"})
                    self.assertEqual(denied.status_code, 429)
                    self.assertEqual(denied.headers["Retry-After"], "60")
                self.assertEqual(create.call_count, 9)
                self.assertEqual(stream.call_count, 1)
                clock.return_value = 160.0
                self.assertEqual(http.post("/chat", json={"message": "hello"}).status_code, 200)
                self.assertEqual(create.call_count, 10)


if __name__ == "__main__":
    unittest.main()
