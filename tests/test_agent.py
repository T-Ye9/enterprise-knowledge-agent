"""真实 LangGraph 执行 + 模拟模型，验证路径、协议与循环限制。"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai.types.chat import ChatCompletionMessageToolCall

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent import AgentLimitError, run_agent


def response(content=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))])


def tool(name="calculator", arguments='{"a":123,"b":456,"operation":"multiply"}', identifier="call_1"):
    return ChatCompletionMessageToolCall(id=identifier, type="function", function={"name": name, "arguments": arguments})


class AgentTests(unittest.TestCase):
    def run_quiet(self, client, question="测试", **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_agent(client, "test-model", question, **kwargs)

    def test_direct_answer_and_state_isolation(self):
        client = Mock()
        client.chat.completions.create.return_value = response("你好！")
        with patch("app.agent.execute_tool") as execute:
            first = self.run_quiet(client, "你好")
            second = self.run_quiet(client, "另一条独立请求")
        execute.assert_not_called()
        self.assertEqual(first["path"], ["START", "agent", "END"])
        self.assertEqual(second["llm_calls"], 1)
        sent = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[1]["content"], "另一条独立请求")

    def test_calculator_result_and_matching_id(self):
        client = Mock()
        client.chat.completions.create.side_effect = [response(calls=[tool()]), response("56088")]
        result = self.run_quiet(client)
        self.assertEqual(result["path"], ["START", "agent", "tools", "agent", "END"])
        self.assertEqual(result["tool_calls"][0]["result"], {"result": 56088})
        sent = client.chat.completions.create.call_args.kwargs
        self.assertEqual(sent["tool_choice"], "auto")
        self.assertEqual(sent["messages"][-1], {"role": "tool", "tool_call_id": "call_1", "content": '{"result": 56088}'})

    def test_knowledge_metadata_returned(self):
        client = Mock()
        client.chat.completions.create.side_effect = [response(calls=[tool("search_knowledge_base", '{"query":"报销？"}')]), response("十个工作日[test.pdf:p2:c1]")]
        evidence = {"results": [{"text": "十个工作日", "metadata": {"source": "test.pdf", "page_number": 2, "chunk_id": "test.pdf:p2:c1"}}]}
        with patch("app.tool_runtime.search_knowledge_base", return_value=evidence):
            result = self.run_quiet(client)
        sent = client.chat.completions.create.call_args.kwargs["messages"][-1]
        self.assertEqual(json.loads(sent["content"]), evidence)
        self.assertEqual(result["tool_calls"][0]["result"], evidence)

    def test_multiple_tools_and_multiple_rounds(self):
        client = Mock()
        client.chat.completions.create.side_effect = [
            response(calls=[tool(identifier="one"), tool(identifier="two")]),
            response(calls=[tool(identifier="three")]), response("完成"),
        ]
        result = self.run_quiet(client)
        self.assertEqual(result["llm_calls"], 3)
        self.assertEqual([call["id"] for call in result["tool_calls"]], ["one", "two", "three"])
        self.assertEqual(result["path"], ["START", "agent", "tools", "agent", "tools", "agent", "END"])

    def test_invalid_tool_arguments_return_error_then_model_recovers(self):
        client = Mock()
        client.chat.completions.create.side_effect = [response(calls=[tool(arguments="{}")]), response("参数有误")]
        result = self.run_quiet(client)
        self.assertIn("error", result["tool_calls"][0]["result"])
        self.assertEqual(result["final_answer"], "参数有误")

    def test_repetition_stops_at_limit_without_extra_tool_execution(self):
        client = Mock()
        client.chat.completions.create.return_value = response(calls=[tool()])
        with patch("app.agent.execute_tool", return_value={"result": 56088}) as execute:
            with self.assertRaises(AgentLimitError):
                self.run_quiet(client, max_llm_calls=2)
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertEqual(execute.call_count, 1)

    def test_invalid_input_and_empty_response(self):
        client = Mock()
        with self.assertRaises(ValueError):
            self.run_quiet(client, " ")
        with self.assertRaises(ValueError):
            self.run_quiet(client, max_llm_calls=0)
        client.chat.completions.create.assert_not_called()
        client.chat.completions.create.return_value = response("")
        with self.assertRaises(ValueError):
            self.run_quiet(client)


if __name__ == "__main__":
    unittest.main()
