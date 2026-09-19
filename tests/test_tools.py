"""不需要 API Key 的离线 calculator 测试。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from main import execute_tool
from tools import calculator


class CalculatorTests(unittest.TestCase):
    def test_arithmetic(self):
        for a, b, operation, expected in [
            (123, 456, "multiply", 56088), (999, 888, "add", 1887),
            (10, 3, "subtract", 7), (9, 2, "divide", 4.5),
        ]:
            with self.subTest(operation=operation):
                self.assertEqual(calculator(a, b, operation), expected)

    def test_invalid_parameters(self):
        for a, b, operation in [
            ("123", 456, "multiply"), (True, 1, "add"),
            (float("nan"), 1, "add"), (1, 2, "power"),
            (float("inf"), 1, "add"), (1e308, 1e308, "multiply"),
        ]:
            with self.subTest(a=a, operation=operation):
                with self.assertRaises(ValueError):
                    calculator(a, b, operation)

    def test_division_by_zero(self):
        with self.assertRaises(ZeroDivisionError):
            calculator(1, 0, "divide")

    def test_dispatch_result(self):
        self.assertEqual(
            execute_tool("calculator", '{"a":123,"b":456,"operation":"multiply"}'),
            {"result": 56088},
        )

    def test_dispatch_errors(self):
        for name, arguments in [
            ("unknown", "{}"), ("calculator", "invalid JSON"),
            ("calculator", "[]"), ("calculator", "{}"),
            ("calculator", '{"a":1,"b":0,"operation":"divide"}'),
            ("calculator", '{"a":1,"b":2,"operation":"add","extra":3}'),
        ]:
            with self.subTest(name=name, arguments=arguments):
                self.assertIn("error", execute_tool(name, arguments))


if __name__ == "__main__":
    unittest.main()
