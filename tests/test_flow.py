"""模拟响应验证消息传递协议，不代表真实模型选工具测试。"""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai.types.chat import ChatCompletionMessageToolCall

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from main import run_conversation


def response(content=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=calls)
    )])


class FlowTests(unittest.TestCase):
    def test_tool_result_returned_with_matching_id(self):
        tool_call = ChatCompletionMessageToolCall(
            id="call_test", type="function",
            function={"name": "calculator", "arguments": '{"a":123,"b":456,"operation":"multiply"}'},
        )
        client = Mock()
        client.chat.completions.create.side_effect = [
            response(calls=[tool_call]), response(content="结果为 56088。"),
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            trace = run_conversation(client, "test-model", "帮我计算 123 * 456")
        self.assertEqual(trace["tool_calls"][0]["result"], {"result": 56088})
        requests = client.chat.completions.create.call_args_list
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].kwargs["tool_choice"], "auto")
        messages = requests[1].kwargs["messages"]
        self.assertEqual(messages[-2]["role"], "assistant")
        self.assertEqual(messages[-2]["tool_calls"][0]["id"], "call_test")
        self.assertEqual(messages[-1], {
            "role": "tool", "tool_call_id": "call_test", "content": '{"result": 56088}',
        })

    def test_direct_answer_does_not_execute_tool(self):
        client = Mock()
        client.chat.completions.create.return_value = response(content="你好！")
        with patch("app.agent.execute_tool") as execute, contextlib.redirect_stdout(io.StringIO()):
            trace = run_conversation(client, "test-model", "你好，请介绍一下你自己。")
        execute.assert_not_called()
        self.assertEqual(trace["tool_calls"], [])
        self.assertEqual(trace["final_answer"], "你好！")
        client.chat.completions.create.assert_called_once()

    def test_repeated_calls_stop_at_limit(self):
        tool_call = ChatCompletionMessageToolCall(
            id="call_repeat", type="function",
            function={"name": "calculator", "arguments": '{"a":1,"b":2,"operation":"add"}'},
        )
        client = Mock()
        client.chat.completions.create.return_value = response(calls=[tool_call])
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            run_conversation(client, "test-model", "计算")
        self.assertEqual(client.chat.completions.create.call_count, 4)


if __name__ == "__main__":
    unittest.main()
