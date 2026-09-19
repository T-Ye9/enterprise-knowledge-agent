"""真实 Agent + 模拟 SDK 分片：参数拼接、来源、错误和断连清理。"""
import asyncio
import contextlib
import io
import json
import time
import unittest
from threading import Lock
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.agent import run_agent
from app.api import app
from app.chat_stream import stream_chat
from app.conversation_memory import ConversationMemory
from app.llm_stream import collect_stream
from test_agent import response as complete_response


def delta(text=None, calls=None, finish=None):
    return NS(choices=[NS(delta=NS(content=text, tool_calls=calls), finish_reason=finish)])


def call(arguments, name=None, identifier=None, index=0):
    return NS(index=index, id=identifier, function=NS(name=name, arguments=arguments))


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
    def __iter__(self):
        return iter(self.chunks)
    def close(self):
        self.closed = True


def parse_sse(text):
    records = []
    for frame in text.split('\n\n'):
        if not frame.strip():
            continue
        lines = frame.splitlines()
        records.append({"event": lines[0][7:], "data": json.loads(lines[1][6:])})
    return records


class StreamingTests(unittest.TestCase):
    def test_nonstream_and_stream_share_same_session(self):
        memory = ConversationMemory()
        client = Mock()
        client.chat.completions.create.side_effect = [complete_response("记住了"),
            FakeStream([delta("上一轮的问题"), delta(finish="stop")])]
        with patch("app.api.MEMORY", memory), patch("app.api.create_client", return_value=(client, "test")), patch("app.chat_stream.create_client", return_value=(client, "test")), TestClient(app) as http, contextlib.redirect_stdout(io.StringIO()):
            first = http.post("/chat", json={"message": "第一轮"})
            self.assertEqual(first.status_code, 200)
            second = http.post("/chat/stream", json={"message": "继续", "session_id": first.json()["session_id"]})
            self.assertEqual(parse_sse(second.text)[-1]["event"], "done")
            users = [m["content"] for m in client.chat.completions.create.call_args.kwargs["messages"] if m["role"] == "user"]
            self.assertEqual(users, ["第一轮", "继续"])
            self.assertEqual(client.close.call_count, 2)

    def test_tool_arguments_assembled_before_execution_and_next_llm(self):
        client = Mock()
        first = FakeStream([delta("准备计算"), delta(calls=[call('{"a":123,', "calculator", "call_stream")]),
                            delta(calls=[call('"b":456,"operation":"multiply"}')]), delta(finish="tool_calls")])
        final = FakeStream([delta("结果是"), delta("56088"), delta(finish="stop")])
        client.chat.completions.create.side_effect = [first, final]
        events = []
        with contextlib.redirect_stdout(io.StringIO()):
            trace = run_agent(client, "test", "123*456", on_event=events.append)
        self.assertEqual(trace["tool_calls"][0]["result"], {"result": 56088})
        messages = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(messages[-1]["tool_call_id"], "call_stream")
        self.assertEqual(json.loads(messages[-1]["content"]), {"result": 56088})
        self.assertTrue(client.chat.completions.create.call_args.kwargs["stream"])
        self.assertEqual(trace["sources"], [])
        self.assertTrue(first.closed and final.closed)
        last_reset = max(i for i, event in enumerate(events) if event["event"] == "reset")
        self.assertEqual(''.join(e["data"]["text"] for e in events[last_reset:] if e["event"] == "delta"), "结果是56088")
        self.assertEqual([e["event"] for e in events if e["event"].startswith("tool_")], ["tool_start", "tool_end"])

    def test_split_citations_verified_before_emission(self):
        client = Mock()
        stream = FakeStream([delta("答复[fake."), delta("pdf:p99:c1]继续"), delta(finish="stop")])
        client.chat.completions.create.return_value = stream
        events = []
        message = collect_stream(client, events.append, messages=[], model="test")
        self.assertIn("fake.pdf", message.content)  # 原始文本交给已有最终核对逻辑处理。
        self.assertEqual(''.join(e["data"]["text"] for e in events), "答复继续")

    def test_truncated_model_stream_fails_and_closes(self):
        client = Mock()
        stream = FakeStream([delta("部分输出"), delta(finish="length")])
        client.chat.completions.create.return_value = stream
        with self.assertRaises(ValueError):
            collect_stream(client, lambda _: None, messages=[], model="test")
        self.assertTrue(stream.closed)

    def test_http_sse_done_and_error_close_client(self):
        memory = ConversationMemory()
        client = Mock()
        client.chat.completions.create.return_value = FakeStream([delta("你"), delta("好"), delta(finish="stop")])
        with patch("app.api.MEMORY", memory), patch("app.chat_stream.create_client", return_value=(client, "test")), TestClient(app) as http, contextlib.redirect_stdout(io.StringIO()):
            response = http.post("/chat/stream", json={"message": "你好"})
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers["content-type"])
            events = parse_sse(response.text)
            self.assertEqual(events[0]["event"], "session")
            self.assertEqual(events[-1]["data"]["answer"], "你好")
            self.assertEqual(events[-1]["event"], "done")
            client.close.assert_called_once()
            identifier = events[0]["data"]["session_id"]
            client.chat.completions.create.side_effect = ValueError("private error")
            failed = http.post("/chat/stream", json={"message": "失败", "session_id": identifier})
            error = parse_sse(failed.text)[-1]
            self.assertEqual(error["event"], "error")
            self.assertEqual(error["data"]["status"], 502)
            self.assertNotIn("private error", failed.text)
            saved = memory.checkpointer.get_tuple({"configurable": {"thread_id": identifier}})
            users = [m["content"] for m in saved.checkpoint["channel_values"]["messages"] if m["role"] == "user"]
            self.assertEqual(users, ["你好"])

    def test_configuration_unknown_session_and_request_validation(self):
        with TestClient(app) as http, patch("app.chat_stream.create_client", side_effect=ValueError("secret configuration")):
            result = http.post("/chat/stream", json={"message": "hi"})
            self.assertEqual(parse_sse(result.text)[-1]["data"]["status"], 503)
            self.assertNotIn("secret configuration", result.text)
            unknown = http.post("/chat/stream", json={"message": "hi", "session_id": "00000000-0000-0000-0000-000000000000"})
            self.assertEqual(parse_sse(unknown.text)[-1]["data"]["status"], 404)
            self.assertEqual(http.post("/chat/stream", json={"message": " "}).status_code, 422)


class DisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_closes_sdk_releases_lock_and_rolls_back(self):
        memory = ConversationMemory()
        lock = Lock()
        client = Mock()
        def slow_chunks():
            for _ in range(20):
                time.sleep(.02)
                yield delta("字")
            yield delta(finish="stop")
        sdk_stream = FakeStream(slow_chunks())
        client.chat.completions.create.return_value = sdk_stream
        with patch("app.chat_stream.create_client", return_value=(client, "test")), contextlib.redirect_stdout(io.StringIO()):
            stream = stream_chat("测试断连", None, memory, lock)
            first = parse_sse(await stream.__anext__())[0]
            while True:
                event = parse_sse(await stream.__anext__())[0]
                if event["event"] == "delta":
                    break
            await stream.aclose()
            for _ in range(100):
                if sdk_stream.closed and not lock.locked():
                    break
                await asyncio.sleep(.01)
            self.assertTrue(sdk_stream.closed)
            self.assertFalse(lock.locked())
            client.close.assert_called_once()
            self.assertIsNone(memory.checkpointer.get_tuple({"configurable": {"thread_id": first["data"]["session_id"]}}))


if __name__ == "__main__":
    unittest.main()
