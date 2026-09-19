"""calculator 的真实 Python 函数及发给模型的工具 Schema。"""

import math

from app.knowledge_tool import MAX_TOP_K


TOOL_DEFINITIONS = [{
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "计算两个数字的加、减、乘或除。需要精确四则运算时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "第一个数字"},
                "b": {"type": "number", "description": "第二个数字"},
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide"],
                    "description": "运算：加、减、乘、除",
                },
            },
            "required": ["a", "b", "operation"],
            "additionalProperties": False,
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": (
            "检索已入库的企业文档，返回相关片段、分数及文件名/页码/chunk ID。"
            "企业制度、工作时间、休假、差旅报销、奖金等企业事实问题应先检索，"
            "即使不确定知识库有没有答案。普通聊天和纯数学计算不需要此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "description": "要检索的企业知识问题"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": MAX_TOP_K,
                          "description": "最多返回多少片段，可省略以使用默认值"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}]


def calculator(a: float, b: float, operation: str):
    """直接执行四则运算，不执行模型提供的代码。"""
    for value in (a, b):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("a 和 b 必须是数字")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("a 和 b 必须是有限数字")
    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    elif operation == "divide":
        if b == 0:
            raise ZeroDivisionError("除数不能为零")
        result = a / b
    else:
        raise ValueError("operation 必须是 add、subtract、multiply 或 divide")
    if isinstance(result, float) and not math.isfinite(result):
        raise ValueError("计算结果超出有限数字范围")
    return result
