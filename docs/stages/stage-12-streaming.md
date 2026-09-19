# 阶段 12：Streaming Response

## 选择：SSE 格式 + POST fetch

当前前端只需要从后端接收模型文本、工具状态及最终来源，是单向数据推送。
使用 text/event-stream（SSE 帧），React 通过 fetch POST 与 ReadableStream 读取。
原生 EventSource 使用 GET，不适合直接沿用 JSON message/session_id 请求；fetch 可以保持现有请求结构。
不引入 WebSocket、连接管理框架或新依赖。原有 POST /chat 保留。

## 文件职责

| 创建/修改 | 文件 | 职责 |
| --- | --- | --- |
| 新增 | app/llm_stream.py | 消费 SDK 原生分片，拼接文本及多条 Tool Call，核对流中 PDF 引用 |
| 修改 | app/agent.py | on_event 可选回调，复用现有图，发送 reset/工具状态，返回值保持兼容 |
| 新增 | app/chat_stream.py | 同步 Agent 的工作线程、异步事件队列、SSE 编码、错误及断连处理 |
| 修改 | app/api.py | 新增 POST /chat/stream，返回 StreamingResponse |
| 修改 | frontend/src/api.ts | StreamEvent 类型、POST fetch、UTF-8 解码、帧缓冲、终止/错误处理 |
| 修改 | frontend/src/App.tsx | 创建 AI 消息占位并逐步更新，工具状态及最终来源，失败移除部分消息 |
| 新增 | tests/test_streaming.py | 七项确定性测试：协议、来源、完成、失败回滚、配置、断连和跨接口会话 |
| 修改 | frontend/e2e/chat.spec.ts | 主流程改用真实 SSE，观察读取分片，生成唯一测试 PDF 及验收记录 |
| 新增 | frontend/e2e/stream.spec.ts | 完成前可见文本、UTF-8 网络分片、error/EOF 结束 loading |
| 修改 | samples/create_web_demo_pdf.py | 支持指定输出路径和制度编号，避免重复样例干扰来源验收 |
| 生成 | samples/streaming_examples.json | 真实流式最终回答、工具与来源、连续会话及新会话记录 |
| 修改 | README.md | 流式入口、验收说明 |
| 新增 | docs/stages/stage-12-streaming.md | 本文 |

没有修改 ingestion、vector store、工具 schema、检索算法或会话存储方案。

## 真实增量而非模拟打字

原来 client.chat.completions.create 等待完整结果。
新的 collect_stream() 调用同一模型、消息、工具定义，额外设置 stream=True：

```python
stream = client.chat.completions.create(**kwargs, stream=True)
for chunk in stream:
    ...
```

每个文本 delta 经引用处理后立即发出事件，不是等完整答案后再按字符切开。
thinking 仍为 disabled，不输出内部 reasoning_content。
模型结束后继续复用原 agent_node 的空回答检查、citation 核对和条件路由。
SDK stream 在 finally 中关闭。

## Tool Calling 链路

```text
用户问题
  → agent：原生 LLM stream
  → 按 Tool Call index 拼接 id/name/arguments
  → 完成整个模型轮
  → assistant 消息保存完整 tool_calls
  → 原条件边决定 tools 或 END
  → tools：发送 tool_start
  → 原 execute_tool(name, 完整 arguments)
  → 保存匹配 tool_call_id 的真实 Tool Result
  → 发送 tool_end
  → 回 agent，必要时继续循环
  → 最终文字逐步发送，最终引用核对
  → END / checkpoint 保存完整轮
  → done 发送完整结果
```

Tool Arguments 可能来自多个增量，例如 `{"a":123,` 和 `"b":456,"operation":"multiply"}`。
collect_stream() 用 call.index 区分同时返回的工具，并将参数字符串拼接完整。
拼接完成前绝不执行 calculator 或 search_knowledge_base。
同一轮的多个工具、多个 agent/tools 循环仍由原图支持；每轮 4 次 LLM 调用的预算不变。
工具参数/结果是独立事件，不当作 AI 答案文字显示。
如果模型先写了一段前言、随后请求工具，reset 会清除本轮临时前言，防止将它误认为最终回答。

## 与现有同步架构的结合

现有 OpenAI SDK、Agent、PDF/embedding 与本地 Qdrant 使用同步调用。
为避免全量重写 async，stream_chat() 使用 asyncio.to_thread 在工作线程执行原 run_agent。
节点通过 on_event 回调，以 loop.call_soon_threadsafe 将事件放入 asyncio.Queue。
异步生成器边消费队列边 yield SSE，等待模型期间不会阻塞 FastAPI 事件循环。
工作线程只在持有原 CHAT_LOCK 时访问 Agent/checkpoint/Qdrant；上传、删除会话和新旧 chat 沿用同一锁。
事件回调、队列、SDK 客户端不进入 AgentState 或 checkpoint，不存储 API Key。

## HTTP 接口与事件契约

请求与旧接口相同：

```http
POST /chat/stream
Content-Type: application/json
Accept: text/event-stream
```

```json
{"message":"帮我计算 123 * 456","session_id":"可选已有UUID"}
```

没有 session_id 会新建会话。响应 Content-Type 为 text/event-stream；
Cache-Control: no-cache，X-Accel-Buffering: no（告知支持该头的代理不要缓冲）。
单个帧：

```text
event: delta
data: {"text":"结果是"}

```

每帧以两个换行分隔，data 使用 JSON 编码，正文中的换行和中文不会破坏帧边界。

| event | data | 前端行为 |
| --- | --- | --- |
| session | session_id | 保存 ID，后续请求带回 |
| reset | {} | 清空本条临时答案，不清空旧对话 |
| delta | text | 追加本条 AI 消息 |
| tool_start | name、完整 arguments | 显示“正在使用工具…” |
| tool_end | name、真实 result | 等待下一次模型输出 |
| done | session_id、answer、sources、path、tool_calls、llm_calls | 用最终核对结果替换临时文字，结束流 |
| error | status、message | 结束流，显示错误，恢复可重试输入 |

done/error 是终止事件。正确完成必须有 done，HTTP 200 或连接关闭本身不表示答案完成。
请求体不合法仍是普通 HTTP 422；开始 SSE 后无法将 HTTP 200 改成 502/504/508，
因此业务错误使用 error 的 status 字段。缺失配置是 503，会话不存在是 404，超时是 504，循环上限是 508。
内部异常详情和密钥不发给前端，沿用简洁错误信息。

## 来源处理

Sources 只在 done 中发送，来自原来的真实 retrieved chunk metadata 核对与去重。
流式文本中的未闭合方括号暂缓显示，完整 PDF 引用交给 resolve_citations() 核对，
不匹配真实证据的 PDF 来源标记不发送到页面。
普通字符仍即时发送；该少量缓冲不是等待完整答案。
最终回答再次沿用阶段 10 的核对逻辑，完成事件中的 answer 是最终版本。
历史 Tool Result 仍可支持后续追问，不需要强制再次检索。
生成过程中的文字尚未完成，不能作为已提交的事实；真实引用也不自动证明语义正确。

## React 如何读取

```ts
const reader = response.body.getReader()
const decoder = new TextDecoder()
const { value } = await reader.read()
buffer += decoder.decode(value, { stream: true })
```

网络 chunk 不等于 SSE event：一个 chunk 可能包含半条 JSON、多条事件或半个 UTF-8 中文字符。
TextDecoder 的 stream:true 保留未完整字符；buffer 保存未完整帧，只处理遇到 \n\n 的事件。
当前服务固定发 LF 分隔帧；这不是通用 EventSource 的全部协议实现。
收到 delta 更新同一个 assistant 占位消息，Sources 在 done 后显示。
工具状态在 loading 区展示，等待期间禁止重复发送、上传和新建会话。

fetch 不会因 HTTP 502 自动抛错，因此先检查 response.ok。
读取过程中 error 事件、网络异常、180 秒总超时、EOF 前未收到 done 都进入同一失败清理逻辑。
finally 取消 reader、结束等待；App.finally 将 busy 设为 false。
失败移除本轮用户消息与部分 assistant 消息，恢复输入，不将部分生成当作成功答案。

## 断连和 checkpoint

SSE async generator 结束或被客户端断开时，finally 设置线程安全 cancelled Event。
下一次节点 emit 检测取消，抛 StreamCancelled；原 run_agent 的异常处理删除失败轮 checkpoint，恢复上一成功轮。
SDK stream/client 关闭，工作线程释放 CHAT_LOCK。
断连测试用慢模型分片验证 stream.close、client.close、锁释放，以及首次失败的 checkpoint 被删除。
上一成功轮的异常回滚也通过 HTTP 测试核对。

取消是协作式：Python 不能立即终止正在等待 SDK 网络响应或执行同步工具的线程。
如果没有新事件，需等当前调用返回或 SDK 超时（已有 60 秒）后清理；工具本身仍按已有同步方式执行。
服务端完成 checkpoint 和客户端收到 done 不是原子事务。若恰在完成附近断网，后端可能已提交成功轮；
前端提示重试或新建会话，本阶段没有请求幂等、断点重连或事件回放。
没有添加 EventSource 自动重连，避免无意重复触发 Agent。
会话仍是单进程短期内存，使用单 worker，重启会清空。

## 非流式兼容

POST /chat、CLI main.py 沿用原来完整返回方式。
run_agent 的 on_event 默认为 None，原客户端不必更改调用方式或 Schema。
流式与非流式共用 MEMORY/checkpointer 和 session_id。
专门测试先调用 /chat，再同 ID 调用 /chat/stream，确认第二轮 LLM 收到第一轮消息。

## 启动和验证

终端 1，项目根目录：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

终端 2，frontend：

```powershell
npm run dev
```

打开 http://127.0.0.1:5173。普通聊天观察逐步文字；计算观察 calculator 状态；企业问题观察检索状态与最终 Sources。
原 /docs 的 /chat 仍可用。直接读取 SSE 时可使用系统 curl.exe：

```powershell
'{"message":"帮我计算 123 * 456"}' | curl.exe -N -X POST http://127.0.0.1:8000/chat/stream -H 'Content-Type: application/json' --data-binary '@-'
```

测试：

```powershell
# 根目录
$env:PYTHONIOENCODING='utf-8'
$env:HF_HUB_OFFLINE='1' # 模型已缓存时使用
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# frontend，两端已启动
npm run build
npm run test:e2e
```

浏览器仍使用本机 Edge。真实主流程需要 DeepSeek 配置、已缓存 embedding 或可下载模型，以及开发依赖 reportlab。
浏览器测试生成带唯一制度编号的公开 PDF 到 tmp/pdfs/（已忽略），避免历史相同样例干扰来源验收。
真实流程包含上传、检索、连续追问、calculator、新会话；这些调用产生真实费用，测试不使用假 LLM。
另外三项流式传输/失败测试使用受控服务器或模拟 SSE，不把它们称作真实模型测试。

## 实际验收结果

2026-09-18：

- 完整后端回归 73 项通过（原 67 项 + 首批 6 项流式测试）；
  后续增加跨接口会话用例，流式 7 项全部重跑通过，当前共有 74 个后端测试。
- TypeScript 检查和 Vite 生产构建通过，无新增依赖。
- 两端实际在 8000 / 5173 运行，6 项浏览器测试全部通过。
- 真实知识库、追问、calculator、普通聊天都有多条 delta，最终 done 返回正确结构。
- 唯一测试制度回答 731 元，引用本轮实际上传 PDF 的第 1 页；追问复用同会话；计算 56088 无来源。
- 受控 SSE 在 done 前延迟分片，页面已显示“你好”且 loading 仍可见；故意拆开“你”的 UTF-8 字节，正文仍正确。
- error 和没有 done 的 EOF 均清除部分消息、恢复输入、结束 loading。
- 真实主流程无 pageerror，流式完成截图已实际查看。
- 真实记录 samples/streaming_examples.json；浏览器报告和截图在 frontend/test-results/（已忽略）。

### 问题定位与修复

第一次真实浏览器测试：页面和后端已完成，但 Playwright response.text() 的调试协议读取 SSE 响应体失败。
改用 response.clone().text() 后，正常结束时的 AbortController 会取消副本，导致等待超时。
最终只在测试中观察页面实际 reader.read() 返回的分片，记录完整 done 帧，避免另一个读取分支。
产品代码没有为了绕过测试而关闭资源清理，也没有将流式改回完整返回。

重复上传相同 PDF 会产生相同内容但不同来源名，Top-K 可能命中历史副本。
测试生成唯一制度编号和独立临时文件，并提问该编号，确保核对本轮上传来源；没有修改检索算法。
确定性后端测试和前端构建没有遇到实现错误。

## 面试知识点

1. SSE 是响应传输格式，模型 stream=True 才提供真实增量，二者不是同一层。
2. Token/网络 chunk/SSE event/完整消息是不同边界，必须分别拼接。
3. Tool Arguments 尚未完整时不能 json.loads 后立即执行工具。
4. 文本可先展示，但 State 要保存完整 assistant/tool 协议，而不是每个 token 一条消息。
5. HTTP 响应开始后，业务失败使用流内 error；只有 done 才表示正常完成。
6. 临时文字与最终核对后的 Answer/Sources 是不同完成状态。
7. 断连要清理资源并处理失败 checkpoint，线程取消是协作式，不等于立即终止同步工作。
8. 保留非流式接口，让脚本和已有客户端无需同步迁移。

参考：[DeepSeek Chat Completions 流式 delta](https://api-docs.deepseek.com/api/create-chat-completion/)。
本项目沿用直接 SDK 和既有同步图；没有额外切换到 LangChain model 或重写 LangGraph。

阶段 12 完成，停止后续开发。
