"""最小 HTTP 层：请求校验、Agent 调用和可理解的错误响应。"""

from collections import deque
from math import ceil
from threading import Lock
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from pydantic import BaseModel, Field, StringConstraints

from .agent import run_agent
from .llm_client import create_client
from .conversation_memory import ConversationMemory
from .document_upload import MAX_UPLOAD_BYTES, InvalidDocument, ingest_upload
from .chat_stream import stream_chat
from pathlib import Path
from time import monotonic, perf_counter
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from .reliability import close_client, error_data, log_event
from contextlib import asynccontextmanager
from .deployment import cors_origins, production, uploads_enabled, validate_deployment
from .demo_bootstrap import bootstrap_demo


load_dotenv(Path(__file__).resolve().parents[1] / ".env")
@asynccontextmanager
async def lifespan(application):
    try:
        validate_deployment()
        bootstrap_demo()
    except Exception as error:
        log_event("startup_configuration_invalid", error=error)
        raise
    yield


app = FastAPI(title="Enterprise Knowledge Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware,
                   allow_origins=cors_origins(),
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])
# Qdrant 本地模式同一路径只能被一个客户端打开，串行处理当前示例的 chat。
CHAT_LOCK = Lock()
MEMORY = ConversationMemory()
CHAT_RATE_LOCK = Lock()
CHAT_REQUEST_TIMES = deque()
CHAT_RATE_LIMIT = 10
CHAT_RATE_WINDOW = 60


def chat_retry_after():
    """单 worker 公开 Demo 的全局聊天额度，不依赖可伪造的客户端 IP。"""
    with CHAT_RATE_LOCK:
        now = monotonic()
        while CHAT_REQUEST_TIMES and CHAT_REQUEST_TIMES[0] <= now - CHAT_RATE_WINDOW:
            CHAT_REQUEST_TIMES.popleft()
        if len(CHAT_REQUEST_TIMES) >= CHAT_RATE_LIMIT:
            return max(1, ceil(CHAT_REQUEST_TIMES[0] + CHAT_RATE_WINDOW - now))
        CHAT_REQUEST_TIMES.append(now)
        return None


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # 默认 validation detail 会回显 input，可能包含敏感问题或请求内容。
    log_event("request_invalid", status=422, error=error)
    return JSONResponse(status_code=422, content={"detail": "请求格式无效，请检查字段类型和必填内容"})


@app.middleware("http")
async def request_logging(request, call_next):
    started = perf_counter()
    if (production() and request.method == "POST"
            and request.url.path in {"/chat", "/chat/stream"}):
        retry_after = chat_retry_after()
        if retry_after is not None:
            log_event("chat_rate_limited", status=429)
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后重试"},
                                headers={"Retry-After": str(retry_after)})
    try:
        response = await call_next(request)
    except Exception as error:
        log_event("request_failed", error=error, status=500)
        return JSONResponse(status_code=500, content={"detail": "服务内部错误，请检查服务日志"})
    log_event("request_completed", status=response.status_code,
              duration_ms=round((perf_counter() - started) * 1000, 1))
    return response


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]
    session_id: UUID | None = None


class SourceResponse(BaseModel):
    document: str
    page: int = Field(ge=1)


class ChatResponse(BaseModel):
    session_id: UUID
    answer: str
    path: list[str]
    tool_calls: list[dict]
    llm_calls: int
    sources: list[SourceResponse] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str


class SessionResponse(BaseModel):
    session_id: UUID


class UploadResponse(BaseModel):
    document: str
    pages: int
    chunks_saved: int


@app.post("/documents", response_model=UploadResponse, status_code=201)
def upload_document(file: Annotated[UploadFile, File()]):
    try:
        if not uploads_enabled():
            raise HTTPException(403, "公开 Demo 不接受文档上传，请使用预置公开知识库")
        if file.size is not None and file.size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "PDF 不能超过 10 MB")
        content = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "PDF 不能超过 10 MB")
        with CHAT_LOCK:
            try:
                return UploadResponse(**ingest_upload(file.filename or "", content))
            except InvalidDocument as error:
                log_event("document_rejected", error=error, status=400)
                raise HTTPException(400, str(error)) from None
            except (ValueError, OSError, RuntimeError) as error:
                log_event("document_ingestion_failed", error=error, status=503)
                raise HTTPException(503, "文档入库失败，请检查本地模型和知识库配置") from None
    finally:
        file.file.close()


@app.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session():
    with CHAT_LOCK:
        return SessionResponse(session_id=MEMORY.create())


@app.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: UUID):
    with CHAT_LOCK:
        identifier = str(session_id)
        if not MEMORY.exists(identifier):
            raise HTTPException(404, "会话不存在，请新建会话")
        MEMORY.delete(identifier)
        return Response(status_code=204)


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok")


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    with CHAT_LOCK:
        identifier = str(request.session_id) if request.session_id is not None else None
        if identifier is not None and not MEMORY.exists(identifier):
            raise HTTPException(404, "会话不存在，请新建会话")
        try:
            client, model = create_client()
        except ValueError as error:
            log_event("llm_configuration_invalid", error=error, status=503)
            raise HTTPException(503, "LLM 配置未就绪，请检查本地 .env") from None
        try:
            identifier = identifier or MEMORY.create()
            trace = run_agent(client, model, request.message,
                              session_id=identifier, checkpointer=MEMORY.checkpointer)
            return ChatResponse(session_id=identifier, answer=trace["final_answer"], path=trace["path"],
                                tool_calls=trace["tool_calls"], llm_calls=trace["llm_calls"],
                                sources=trace.get("sources", []))
        except Exception as error:
            failure = error_data(error)
            log_event("chat_failed", error=error, status=failure["status"])
            raise HTTPException(failure["status"], failure["message"]) from None
        finally:
            close_client(client)


@app.post("/chat/stream", response_class=StreamingResponse)
def chat_stream(request: ChatRequest):
    identifier = str(request.session_id) if request.session_id is not None else None
    return StreamingResponse(stream_chat(request.message, identifier, MEMORY, CHAT_LOCK),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
