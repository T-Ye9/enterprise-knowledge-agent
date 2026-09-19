"""真实 API 验收，会消耗 API 额度；未配置密钥时明确跳过。"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from main import create_client, run_conversation


class LiveAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.client, cls.model = create_client()
        except ValueError as error:
            raise unittest.SkipTest(str(error))

    def check_calculation(self, question, a, b, operation, expected):
        trace = run_conversation(self.client, self.model, question)
        calls = trace["tool_calls"]
        self.assertTrue(calls, "LLM 没有请求工具调用")
        self.assertTrue(any(
            call["name"] == "calculator"
            and json.loads(call["arguments"]) == {"a": a, "b": b, "operation": operation}
            and call["result"] == {"result": expected}
            for call in calls
        ), "模型参数或真实计算结果不符合预期")
        self.assertIn(str(expected), trace["final_answer"].replace(",", ""))

    def test_1_multiply(self):
        self.check_calculation("帮我计算 123 * 456", 123, 456, "multiply", 56088)

    def test_2_add(self):
        self.check_calculation("帮我计算 999 + 888", 999, 888, "add", 1887)

    def test_3_greeting(self):
        trace = run_conversation(self.client, self.model, "你好，请介绍一下你自己。")
        self.assertEqual(trace["tool_calls"], [], "问候时不应调用工具")
        self.assertTrue(trace["final_answer"])


if __name__ == "__main__":
    unittest.main()
