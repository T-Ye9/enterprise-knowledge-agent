"""消费真实模型增量，完整拼接 Tool Call；不执行工具。"""
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall

from .citations import resolve_citations


def collect_stream(client, emit, **kwargs):
    content = ""
    visible = ""
    calls = {}
    finish = None
    stream = client.chat.completions.create(**kwargs, stream=True)
    try:
        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish = choice.finish_reason or finish
            delta = choice.delta
            for call in delta.tool_calls or []:
                assembled = calls.setdefault(call.index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                assembled["id"] += call.id or ""
                if call.function:
                    assembled["function"]["name"] += call.function.name or ""
                    assembled["function"]["arguments"] += call.function.arguments or ""
            content += delta.content or ""
            # 工具轮的前言不作为最终答案；不向页面发送参数 JSON。
            if calls:
                continue
            display = content
            # 暂缓不完整方括号，防止分片 PDF 引用绕过来源核对。
            if display.rfind("[") > display.rfind("]"):
                display = display[:display.rfind("[")]
            display, _ = resolve_citations(display, kwargs["messages"])
            if len(display) > len(visible):
                emit({"event": "delta", "data": {"text": display[len(visible):]}})
                visible = display
        if finish not in {"stop", "tool_calls"}:
            raise ValueError("模型流未正常完成，可能被截断")
        if finish == "tool_calls" and not calls:
            raise ValueError("模型流缺少 Tool Call")
        if calls:
            emit({"event": "reset", "data": {}})
        return ChatCompletionMessage(role="assistant", content=content or None,
                                     tool_calls=[ChatCompletionMessageToolCall(**calls[index]) for index in sorted(calls)] or None)
    finally:
        stream.close()
