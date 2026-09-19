"""同步 Agent 在工作线程执行，异步 SSE 持续消费事件。"""
import asyncio
import json
from threading import Event

from fastapi import HTTPException

from .agent import run_agent
from .llm_client import create_client
from .reliability import close_client, error_data, log_event


class StreamCancelled(Exception):
    pass


async def stream_chat(message, session_id, memory, lock):
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    cancelled = Event()

    def emit(event):
        if cancelled.is_set():
            raise StreamCancelled()
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def produce():
        client = None
        try:
            with lock:
                if cancelled.is_set():
                    return
                if session_id is not None and not memory.exists(session_id):
                    raise HTTPException(404, "会话不存在，请新建会话")
                try:
                    client, model = create_client()
                except ValueError:
                    raise HTTPException(503, "LLM 配置未就绪，请检查本地 .env") from None
                identifier = session_id or memory.create()
                try:
                    emit({"event": "session", "data": {"session_id": identifier}})
                    trace = run_agent(client, model, message, session_id=identifier,
                                      checkpointer=memory.checkpointer, on_event=emit)
                    emit({"event": "done", "data": {"session_id": identifier, "answer": trace["final_answer"],
                         "sources": trace["sources"], "path": trace["path"], "tool_calls": trace["tool_calls"], "llm_calls": trace["llm_calls"]}})
                finally:
                    close_client(client)
                    client = None
        except StreamCancelled:
            log_event("stream_cancelled")
        except Exception as error:
            log_event("stream_failed", error=error, status=error_data(error)["status"])
            if not cancelled.is_set():
                emit({"event": "error", "data": error_data(error)})
        finally:
            if client is not None:
                close_client(client)

    worker = asyncio.create_task(asyncio.to_thread(produce))
    try:
        while True:
            item = await queue.get()
            yield f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
            if item["event"] in {"done", "error"}:
                await worker
                return
    finally:
        cancelled.set()
