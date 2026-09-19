"""仅记录固定事件和安全字段；不记录异常正文、参数、回答或文档。"""
import json
import logging

from fastapi import HTTPException
from langgraph.errors import GraphRecursionError
from openai import APITimeoutError, OpenAIError


logger = logging.getLogger("knowledge_agent")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def log_event(event, *, error=None, **fields):
    # 白名单防止今后意外把业务正文加进日志。
    safe = {key: value for key, value in fields.items()
            if key in {"status", "llm_calls", "tool_requested", "node", "duration_ms"}}
    if error is not None:
        safe["error_type"] = type(error).__name__
    logger.log(logging.WARNING if error is not None else logging.INFO,
               json.dumps({"event": event, **safe}, ensure_ascii=False))


def error_data(error):
    # 局部导入避免 agent → reliability → agent 循环。
    from .agent import AgentLimitError
    if isinstance(error, HTTPException):
        return {"status": error.status_code, "message": error.detail}
    if isinstance(error, (AgentLimitError, GraphRecursionError)):
        return {"status": 508, "message": "Agent 达到循环上限，未获得最终回答"}
    if isinstance(error, APITimeoutError):
        return {"status": 504, "message": "LLM 请求超时"}
    if isinstance(error, OpenAIError):
        return {"status": 502, "message": "LLM 服务调用失败"}
    if isinstance(error, (ValueError, OSError, RuntimeError)):
        return {"status": 502, "message": "Agent 执行失败，请检查服务日志和知识库配置"}
    return {"status": 500, "message": "服务内部错误，请检查服务日志"}


def close_client(client):
    """清理失败单独记录，不覆盖原始请求错误或阻断 SSE 结束事件。"""
    try:
        client.close()
    except Exception as error:
        log_event("client_cleanup_failed", error=error)
