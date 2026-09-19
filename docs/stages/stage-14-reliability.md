# Stage 14：Engineering Reliability

本阶段检查后端、Agent、工具、解析/入库、向量库、配置和 React 错误路径，只完善工程可靠性。没有新增用户功能、依赖、服务或框架。

## 检查发现与处理

原有 Agent 使用 print() 输出用户问题、完整 Tool Arguments、Tool Result 和最终答案，服务运行时可能将检索正文写入日志。现改为安全的固定事件。
原有 HTTP 与 SSE 的错误分类分散，部分 RuntimeError 没有处理。现在共用 error_data()，非预期异常有明确 500，不能泄露异常正文。
默认请求校验 detail 会包含无效 input，现在统一返回不含输入的 422。
上传原先把所有 index_pdf() 的 ValueError 都当作文档无效，可能误把数据库配置故障当成 400。现在 DocumentError 区分文档错误，普通入库 ValueError 返回 503。
前端原有 loading/finally、错误提示及中断恢复保持；补充无效 JSON 和主要流式字段类型检查。

## 文件职责

| 文件 | 修改职责 |
| --- | --- |
| app/reliability.py（新增） | log_event()、error_data()、close_client()，安全日志与共用错误转换 |
| app/agent.py | 用基础日志替换业务正文 print；失败记录后保留原有 checkpoint 回滚并重新抛出 |
| app/api.py | 请求状态/耗时日志、422 不回显输入、HTTP 异常分类、上传失败日志、安全关闭客户端 |
| app/chat_stream.py | 共用错误分类，记录流式失败/取消，关闭异常不阻断终止事件 |
| app/tool_runtime.py | 未知工具和参数失败返回固定错误；运行异常记录后作为明确 Tool Result 回传 |
| app/llm_client.py | 检查 key、base URL、model，保留 60 秒 SDK 超时和零自动重试 |
| app/document_processing.py | 声明 DocumentError，损坏/加密 PDF 错误可识别 |
| app/knowledge_base.py | 空文本块抛出 DocumentError，写库前停止 |
| app/document_upload.py | 仅将文档错误转为 InvalidDocument，服务故障交给 API 分类 |
| app/main.py | 终端明确显示回答；Agent 内部不再打印业务正文 |
| frontend/src/api.ts | 无效 JSON/流式结构给出可理解的错误 |
| tests/test_reliability.py（新增） | 11 个故障测试方法，包括 HTTP/SSE、配置、日志、工具及上传 |
| tests/test_document_upload.py | 既有空文档测试改用明确 DocumentError |
| frontend/e2e/reliability.spec.ts（新增） | 断网、HTTP、JSON、结构、超时的浏览器验证 |
| README.md | 阶段说明及验证入口 |

## 日志与敏感信息

log_event() 使用 Python 标准 logging；格式为时间、级别和 JSON 事件。例：

```text
WARNING {"event": "chat_failed", "status": 504, "error_type": "APITimeoutError"}
INFO {"event": "agent_decision", "llm_calls": 1, "tool_requested": true}
```

字段白名单仅允许 status、llm_calls、tool_requested、node、duration_ms；异常只记录类型。
不输出 str(error)、traceback、HTTP 请求体、请求 URL、工具名称/参数/正文、回答、来源文件名或凭据。不启用第三方 SDK 的 DEBUG 日志。
日志用于知道哪一层失败，完整工具 trace 仍作为原有 API 数据返回给当前使用者，不能当作服务日志随意保存。
已有解析/切分/检索 CLI 的 JSON 输出是显式数据导出，用来本地学习验收，不是服务运行日志；处理敏感文档时不要把这些输出当作公开报告。

## 失败分类

| 场景 | 行为 |
| --- | --- |
| 无效 HTTP 字段、空 message、无效 UUID | HTTP 422，不回显输入，不调用 LLM |
| 不存在的 session | 404；流式入口发送 error(status=404) |
| 缺少/占位 key、无效 base URL、空 model | 503，提示检查本地 .env |
| LLM timeout | 504 |
| LLM 连接、认证、限流及其他 OpenAIError | 502，不输出供应商错误正文 |
| Agent 迭代/工具数量上限 | 508，不继续执行无法回传给模型的工具 |
| Agent 执行 ValueError/OSError/RuntimeError | 502 |
| 其他未预期服务异常 | 500，安全消息及异常类别日志 |
| 工具参数非法、JSON 非对象、未知工具、除零 | 返回带 error 的 Tool Result，由 LLM 处理，不执行模型提供的代码 |
| 知识工具内部运行失败，包括本地 DB 文件锁 | 记录错误，返回明确失败 Tool Result，不伪装为空检索 |
| 上传非 PDF、损坏、加密、0 页、无文本 | 400，明确文档错误；不写入空知识库块 |
| 文件过大 | API 413（既有 10 MB 限制） |
| 模型加载/数据库入库配置或运行故障 | 503，不冒充 PDF 内容错误 |
| 前端断网、非 JSON 错误页、超时、无效数据、SSE error/EOF | 显示错误，结束 loading，移除失败的部分回答并恢复问题输入 |

SSE 发出 HTTP 200 后，不能再修改 HTTP 状态；错误通过 `event: error` 的 status/message 表达。发生错误不发送 done。两种聊天接口共用同样的分类逻辑。

## 关键代码与控制流程

error_data() 把内部异常转换为固定公开消息。API 捕获异常后先 log_event()，再抛 HTTPException；SSE 记录后发送 error。
run_agent() 的宽泛捕获是为了回滚失败轮的 checkpoint，记录后重新抛出，不吞错。VectorStore 初始化的既有捕获用于关闭客户端后重新抛出，也不是静默忽略。
execute_tool() 的宽泛捕获只在真实工具执行边界，将故障转为明确 error 结果，并记录类型；模型仍可按现有循环规则改参数或如实报告失败。
close_client() 单独捕获清理异常并记录 client_cleanup_failed，防止关闭故障覆盖原始 504 或阻断 SSE 结束事件。清理失败不能保证底层资源已释放，日志会明确记录。

文档流仍为 `ingest_upload → index_pdf → extract_pdf → chunk_pages → embedding → save_chunks`。空文档在 embedding/写入前检查，临时文件与已打开的 store 在原有 finally 中清理。
新增 DocumentError 是 ValueError 子类，既有解析入口和调用者的 ValueError 兼容处理仍有效。

## 配置与超时

配置继续来自项目根目录 .env；系统环境变量优先，不覆盖已有环境变量。
检查 DEEPSEEK_API_KEY 非空及既有占位值、DEEPSEEK_MODEL 非空。
DEEPSEEK_BASE_URL 必须是 HTTP(S)、有主机名且没有用户名/密码、查询参数或 fragment；错误不包含具体配置值。
客户端只在需要 LLM 时初始化；/health 仍仅检查服务存活，不代表 LLM、密钥权限或向量库都可用。

保持 SDK timeout=60.0、max_retries=0，前端 180 秒终止请求，Agent 最多 4 次 LLM 调用、每轮最多 8 个工具。
SDK 超时不等于整个 Agent 的总时限；流式持续有数据时也不是严格的 60 秒总期限。前端终止只会取消连接，当前同步模型/工具操作需要返回后才能协作结束。
本阶段不增加后台任务、强制线程终止或重试框架。POST 自动重试可能造成重复入库/对话，因此未引入。
本地 Qdrant 仍采用单 worker 和 CHAT_LOCK，未改造成并发服务器，也未新增 readiness API。

## 测试与结果（2026-09-18）

在项目根目录：

```powershell
# 快速故障测试，不需要真实 LLM
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_reliability.py -v
# 完整后端回归；真实 API 测试读取已有本地配置
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

在 frontend 目录，启动现有 npm run dev 后：

```powershell
npm run build
npm run test:e2e -- e2e/reliability.spec.ts e2e/stream.spec.ts
```

实际结果：最终后端 95 项测试全部通过，其中包含三个真实 DeepSeek 测试（乘法、加法、普通聊天）。新增故障专用 11 项通过。
TypeScript 检查及 Vite 生产构建通过；Edge 浏览器 8 项测试通过（新增 5 项故障场景，加既有增量显示、error、EOF 三项）。
故障使用 mock 注入，但实际运行 FastAPI、LangGraph 和 React 控制流程。没有通过真实供应商制造限流或超时，也没有损坏实际知识库。
超时浏览器测试只将现有 180 秒计时器缩短为 100 毫秒，验证同一取消分支，无需等待三分钟。
日志测试使用人为 private marker，断言问题、工具正文、异常正文、apikey 字段均不进入日志；不是读取真实密钥做测试。
既有循环上限、超量工具、会话回滚、SDK stream 关闭、断连释放锁、上传清理、向量维度校验和持久化测试均继续通过。
损坏 PDF 测试可能出现 pypdf 固定诊断“EOF marker not found”，不包含文档正文。

## 如何运行与验收

启动方式不变：项目根目录 `.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000`，frontend 目录 `npm run dev`。
已有后端没有开启 reload，需重启自己的进程后加载本阶段修改。
访问 /health 应返回 status=ok；聊天和上传正常流程仍可用。
运行上述故障测试，检查状态码、终止事件、资源关闭和日志断言通过；浏览器测试检查错误出现后发送按钮重新可用，没有保留部分错误答案。

这一阶段让故障可见、可解释、可测试，不代表已具备生产环境的进程隔离、数据库事务、并发治理或完整语义响应校验。阶段 14 到此停止。
