"""真实 checkpoint + 模拟模型：三轮、隔离、删除、失败回滚。"""
import contextlib
import io
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from test_agent import response, tool
from app.agent import run_agent
from app.api import app
from app.conversation_memory import ConversationMemory


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.memory = ConversationMemory()
        self.session = self.memory.create()
        self.client = Mock()

    def run_turn(self, question, session=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_agent(self.client, "test", question, session_id=session or self.session,
                             checkpointer=self.memory.checkpointer)

    def test_three_turns_preserve_messages_and_reset_budget(self):
        self.client.chat.completions.create.side_effect = [
            response(calls=[tool()]), response("56088"), response("再加100是56188"), response("再除以2是28094")]
        first = self.run_turn("123乘456")
        second = self.run_turn("再加100")
        third = self.run_turn("再除以2")
        sent = self.client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual([m["content"] for m in sent if m["role"] == "user"], ["123乘456", "再加100", "再除以2"])
        self.assertTrue(any(m["role"] == "tool" for m in sent))
        self.assertEqual(sum(m["role"] == "system" for m in sent), 1)
        self.assertEqual([first["llm_calls"], second["llm_calls"], third["llm_calls"]], [2, 1, 1])
        self.assertEqual(third["tool_calls"], [])

    def test_sessions_do_not_share_history(self):
        self.client.chat.completions.create.return_value = response("好的")
        self.run_turn("我是小明")
        self.run_turn("我是谁", self.memory.create())
        sent = self.client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(len(sent), 2)
        self.assertNotIn("小明", str(sent))

    def test_failure_restores_last_complete_turn(self):
        self.client.chat.completions.create.return_value = response("记住了")
        self.run_turn("我是小明")
        self.client.chat.completions.create.side_effect = [response(calls=[tool()]), ValueError("upstream failed")]
        with self.assertRaises(ValueError):
            self.run_turn("失败轮")
        self.client.chat.completions.create.side_effect = None
        self.client.chat.completions.create.return_value = response("小明")
        self.run_turn("我是谁")
        sent = self.client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual([m["content"] for m in sent if m["role"] == "user"], ["我是小明", "我是谁"])
        self.assertFalse(any(m.get("tool_calls") for m in sent))

    def test_api_create_reuse_delete_and_unknown(self):
        self.client.chat.completions.create.return_value = response("好的")
        with patch("app.api.MEMORY", self.memory), patch("app.api.create_client", return_value=(self.client, "test")), TestClient(app) as http:
            created = http.post("/sessions")
            self.assertEqual(created.status_code, 201)
            identifier = created.json()["session_id"]
            with contextlib.redirect_stdout(io.StringIO()):
                for text in ["我是小明", "我是谁", "继续"]:
                    result = http.post("/chat", json={"message": text, "session_id": identifier})
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(result.json()["session_id"], identifier)
            self.assertEqual(http.delete("/sessions/" + identifier).status_code, 204)
            self.assertFalse(self.memory.exists(identifier))
            self.assertIsNone(self.memory.checkpointer.get_tuple({"configurable": {"thread_id": identifier}}))
            self.assertEqual(http.post("/chat", json={"message": "hi", "session_id": identifier}).status_code, 404)
            self.assertEqual(http.delete("/sessions/" + str(uuid4())).status_code, 404)
            self.assertEqual(http.post("/chat", json={"message": "hi", "session_id": "invalid"}).status_code, 422)
            with contextlib.redirect_stdout(io.StringIO()):
                fresh = http.post("/chat", json={"message": "新问题"})
            self.assertEqual(fresh.status_code, 200)
            self.assertEqual(len(self.client.chat.completions.create.call_args.kwargs["messages"]), 2)


if __name__ == "__main__":
    unittest.main()
