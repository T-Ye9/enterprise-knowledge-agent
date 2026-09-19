# Enterprise Knowledge Agent（企业知识库智能助手）

## Stage 16：Deployment Readiness

已选本地部署方案：Railway 后端（至少 1GiB）与 Render 静态前端；尚未进行外部部署。方案比较与上线清单见
[stage-16-deployment.md](docs/stages/stage-16-deployment.md)。
Railway 首次部署操作与全部环境变量见 [RAILWAY_DEPLOY.md](docs/RAILWAY_DEPLOY.md)。
生产配置模板为 `.env.production.example`，不要覆盖现有 .env 密钥。
生产模式启动时检查密钥、明确 CORS 和可写存储目录；公开 Demo 关闭上传，并通过 `BOOTSTRAP_DEMO_KNOWLEDGE_BASE=true` 在启动时重建两份预置公开 PDF 的知识库。
前端构建需要同时设置 VITE_ALLOW_DOCUMENT_UPLOAD=false，隐藏上传入口；后端仍独立拒绝上传。
后端生产环境的 `/chat` 与 `/chat/stream` 共用每 60 秒 10 次的全局限流，超过返回 429 和 `Retry-After`。额度保存在单 worker 内存中，进程重启会重置。

```powershell
# 项目根目录：部署配置专项测试，不调用真实 LLM
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_deployment.py -v
# 生产启动入口，先设置模板中的实际环境变量；PORT 默认 8000
.\.venv\Scripts\python.exe -m app.server
```

单实例、单 worker；此 Demo 不挂持久卷，KNOWLEDGE_DB_PATH 与 EMBEDDING_CACHE_DIR 指向容器内可写绝对路径。
同源 Compose 默认 /api；静态托管前端需在构建时设置实际 HTTPS VITE_API_URL，并在后端 CORS_ORIGINS 填准确前端 origin。
本机验证：后端 109 项测试通过；生产 Docker 镜像已构建，容器内依赖检查和 `/health` 启动检查通过。Railway 中手动设置健康检查路径 `/health`，启动超时 300 秒；新的 Railway 服务已不支持旧的 `railway.json` 配置方式。
`samples/*.json` 与 `evaluation/reports/` 是验收脚本生成的本地结果，不提交；测试源码、评测数据集和两份公开 PDF 保留在仓库。

## Stage 15：Docker Compose 启动

需要已启动的 Docker Engine 和 Docker Compose v2（Windows 使用 Docker Desktop 的 Linux containers）。
在项目根目录操作；首次使用复制 .env.example 为 .env 并填写 DeepSeek key，已有 .env 请保留。

```powershell
# 仅在尚无 .env 时执行，随后在本地编辑密钥
Copy-Item .env.example .env
docker compose build
docker compose up -d --wait
docker compose ps
```

打开 http://127.0.0.1:8080；API 文档 http://127.0.0.1:8001/docs。
前端通过同源 /api 代理，不需要修改本地开发用的 frontend/.env.local。
后端密钥通过运行时 env_file 注入；不复制进镜像，也不发送给前端。
端口可在根目录 .env 设置 WEB_PORT、BACKEND_PORT 后重新启动，默认 8080/8001。

第一次处理 PDF 需下载 embedding 模型，可以先预热并等待完成：

```powershell
docker compose exec backend python -c "from app.embeddings import Embedder; Embedder()"
# 需本地已有项目 Python 环境；脚本测试真实 LLM 并上传公开样例
.\.venv\Scripts\python.exe samples/verify_docker.py
docker compose logs --tail 50
docker compose down
```

向量库和模型缓存保存在 Docker named volumes，普通 down 不删除；不要使用 down -v，除非确实要清空数据。
容器知识库与本机 data/vector-db 独立，首次为空，可从页面上传 samples/web-demo-policy.pdf。
多轮会话仍只在后端进程内保存，重启会丢失。
不要将会展开运行时密钥的 docker compose config 输出公开。

**验证状态：容器配置已准备，本机尚未安装/启动 Docker，实际镜像 build 和容器验收尚未完成。**
已通过使用 /api 的本地前端构建及验收脚本语法检查。
具体设计与待验证项目见 [stage-15-docker.md](docs/stages/stage-15-docker.md)。

## Stage 14：Engineering Reliability

增加安全的基础日志、HTTP/SSE 共用错误分类、配置检查及关键故障测试。
日志不记录用户问题、回答、工具参数、检索正文、文件名或 API Key。
PDF 无效/无文本与模型或数据库入库失败分别处理；异常不会被静默忽略。
没有新增依赖，启动方式不变；已经运行的后端需重启才能加载修改。

```powershell
# 项目根目录：所有后端测试（真实 LLM 测试需要现有 .env）
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# 只运行故障测试，不调用真实 LLM
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_reliability.py -v
# frontend 目录，先启动 npm run dev
npm run build
npm run test:e2e -- e2e/reliability.spec.ts e2e/stream.spec.ts
```

本阶段验证：95 项后端测试、8 项浏览器测试及生产构建通过。
详细说明见 [stage-14-reliability.md](docs/stages/stage-14-reliability.md)。

## Stage 13：RAG / Agent Evaluation

19 条公开样例问题，分别评估直接检索、真实 Agent 和已有记录的确定性重新评分。
复用现有 ingestion、retrieval 和 Agent，在临时知识库运行；不修改服务数据，不新增依赖。
无需启动前后端，在项目根目录执行：

```powershell
# 只检索，不调用 LLM；首次使用需要下载现有 embedding 模型
.\.venv\Scripts\python.exe -m evaluation.run --mode retrieval --output evaluation/reports/my-retrieval
# 真实 Agent，读取现有 .env 中的 DeepSeek 配置
.\.venv\Scripts\python.exe -m evaluation.run --mode agent --output evaluation/reports/my-agent
# 重评已保存的真实记录，不调用 LLM 或重新检索
.\.venv\Scripts\python.exe -m evaluation.run --mode replay --input evaluation/reports/agent.json --output evaluation/reports/my-replay
.\.venv\Scripts\python.exe -m unittest tests.test_evaluation -v
```

输出同名 JSON 完整记录和 Markdown 报告。退出码 1 表示至少一项质量检查失败，仍会生成报告。
当前直接检索证据覆盖 10/11；Agent 工具选择 19/19，答案依据规则 11/11，拒答规则 3/3。
这些是小型开发集的规则检查，不是系统在所有问题上都可靠的证明。
当前报告见 [agent-rescored.md](evaluation/reports/agent-rescored.md)，
方法、失败案例与评分修正见 [stage-13-evaluation.md](docs/stages/stage-13-evaluation.md)。

## Stage 12：Streaming Response

页面默认通过 `POST /chat/stream` 的 SSE 事件逐步显示真实模型输出。
工具参数完整拼接后才执行；完成时显示核对后的回答和 Sources。
原有 `POST /chat` 保留，可与流式入口使用同一 session_id。
没有新增依赖或 WebSocket。

启动仍与阶段 11 相同：项目根目录启动 uvicorn，frontend 目录运行 npm run dev。
打开 http://127.0.0.1:5173 发送问题，观察文字逐步出现；工具阶段显示工具名。

```powershell
# 项目根目录
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# frontend，两端服务已启动
npm run build
npm run test:e2e
```

流式完成、错误、EOF、中文分片与工具协议说明见
[stage-12-streaming.md](docs/stages/stage-12-streaming.md)。
真实流式验收记录见 `samples/streaming_examples.json`。

## Stage 11：React Web UI

简洁的 React + TypeScript + Vite 页面，包含聊天、来源、loading、错误、连续会话和 PDF 上传。
后端上传复用 index_pdf：解析 → 切分 → embedding → Qdrant。原 Agent 和检索流程保持不变。

终端 1，在项目根目录启动后端：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

终端 2，启动前端：

```powershell
cd frontend
npm ci
npm run dev
```

打开 http://127.0.0.1:5173 。已有测试知识库可以直接提问；也可上传公开测试文件
`samples/web-demo-policy.pdf`，问“Project Cedar 每月健康补贴是多少元？”，应回答 731 元并展示第 1 页来源。
前端 API 地址在 `frontend/.env.local` 配置 `VITE_API_URL`，模板见 `frontend/.env.example`。
后端 `.env` 可配置 `CORS_ORIGINS`，默认允许 localhost / 127.0.0.1 的 5173 端口；修改后重启服务。
API Key 只放在后端 `.env`，不放进 VITE_* 变量。
使用单 worker，前后端已启动时直接访问，不要重复启动占用同一端口。

验收：根目录运行 Python 测试；两个服务运行期间在 frontend 中运行浏览器测试：

```powershell
# 项目根目录
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# frontend 目录
npm run build
npm run test:e2e
```

浏览器测试默认使用本机 Microsoft Edge；完整说明见 [stage-11-react.md](docs/stages/stage-11-react.md)。

## Stage 10：可验证的文档来源

`POST /chat` 新增 `sources: [{"document":"demo-company-policy.pdf","page":2}]`。
Python 将回答的 chunk 引用与真实知识检索结果核对，再从 metadata 提取文件名和页码，同页去重。
普通聊天和计算返回 `sources: []`；追问可引用历史检索证据。原有响应字段保留。

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe samples/verify_citations.py
```

验收脚本使用自己的 TestClient 进程，无需先启动服务。
说明见 [stage-10-citations.md](docs/stages/stage-10-citations.md)，真实结果见 `samples/citation_examples.json`。

## Stage 09：短期多轮会话

使用 LangGraph InMemorySaver，在单个服务进程中按 session_id 保存消息和工具证据。
POST /chat 不传 session_id 会新建会话并返回 ID；下一轮带回同一 ID。
POST /sessions 显式新建会话；DELETE /sessions/{session_id} 删除历史和 ID。
服务重启会丢失会话；使用单 worker。没有增加依赖、数据库或长期记忆。

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
# 以下脚本在自己的进程中验收，无需先启动服务。
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe samples/verify_conversation.py
```

访问 http://127.0.0.1:8000/docs，发送 `{"message":"出差回来后多久提交报销？"}`，
复制响应 session_id，再发送 `{"message":"那要提交哪些材料？","session_id":"复制的ID"}`。
详细说明见 [stage-09-conversation-memory.md](docs/stages/stage-09-conversation-memory.md)，
真实三轮记录见 `samples/conversation_examples.json`。下方是各阶段历史说明。

## Stage 08：LangGraph Agent + 最小 FastAPI 层

终端及 HTTP 都调用两个节点的单 Agent：agent → tools → agent，或 agent → END。
复用原有工具和 RAG，最多 4 次 LLM 调用，返回执行路径和工具 trace。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app/main.py
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

访问 `/docs` 验证 `POST /chat`，请求为 `{"message":"帮我计算 123 * 456"}`。
响应包含 answer、path、tool_calls、llm_calls；`GET /health` 返回 status=ok。
使用单 worker；不要同时运行其它访问同一路径的向量库命令。
真实验收脚本：`samples/verify_agent.py`，完整记录：`samples/agent_examples.json`。
说明见 [stage-08-langgraph-agent.md](docs/stages/stage-08-langgraph-agent.md)。

## Stage 07：Knowledge Search Tool

原生 Tool Calling 同时提供 calculator 和 search_knowledge_base，由 LLM 自主选择。
企业检索复用已有 search_query()，返回正文及完整来源，再由外层 LLM 回答。
资料不足要求明确拒答，不使用 LangGraph，不新增依赖。

```powershell
.\.venv\Scripts\python.exe app/main.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_knowledge_tool.py -v
.\.venv\Scripts\python.exe samples/verify_knowledge_tool.py
```

真实验收记录见 `samples/knowledge_tool_examples.json`。
详细说明见 [stage-07-knowledge-tool.md](docs/stages/stage-07-knowledge-tool.md)。

## Stage 06：基础 RAG Pipeline

复用已有向量库：问题 → 检索 → Top-K context → LLM → 回答及来源。
不重新入库；资料不足要求明确拒答。API Key 继续读取 .env。

```powershell
.\.venv\Scripts\python.exe -m app.rag '出差回来后，多久之内要提交报销？' --top-k 3
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_rag.py -v
.\.venv\Scripts\python.exe samples/verify_rag.py
```

真实问答会将检索正文发送到 LLM API，消耗额度。公开示例见 `samples/rag_examples.json`。
输出包含 answer、retrieved_chunks、context 和 sources，保留全部来源 metadata。
普通终端聊天仍使用 `app/main.py`，与 RAG 入口分离。
详细说明见 [stage-06-rag.md](docs/stages/stage-06-rag.md)。

## Stage 05：本地 Embedding 与向量数据库

使用中文 FastEmbed 模型和 Qdrant 本地模式，无需 API Key、数据库服务或 Docker。
首次下载约 90 MB 模型，在 CPU 生成向量。检索只返回 chunks，不生成答案。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.knowledge_base index samples/demo-company-policy.pdf --chunk-size 80 --overlap 20
.\.venv\Scripts\python.exe -m app.knowledge_base search '出差回来后，多久之内要提交报销？' --top-k 2
```

Top-K 默认 3，可配置。结果包括分数、正文和全部来源 metadata。
数据库位于 `data/vector-db/`，模型缓存位于 `.cache/embeddings/`，均被 Git 忽略。
真实模型验收脚本：`samples/verify_vector_search.py`。
详细记录见 [stage-05-embedding-vector-db.md](docs/stages/stage-05-embedding-vector-db.md)。

## Stage 04：Document Chunking

按页进行字符滑动窗口切分，默认最多 500 字符、重叠 50 字符。
每块保留文件名和页码，并增加 chunk ID 与字符位置。无需新增依赖。

```powershell
.\.venv\Scripts\python.exe -m app.chunking samples/demo-company-policy.pdf --chunk-size 80 --overlap 20
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_chunking.py -v
```

示例参数将公开样本切为 3 块，实际结果见 `samples/chunk_examples.json`。
阶段说明见 [stage-04-chunking.md](docs/stages/stage-04-chunking.md)。
本阶段没有实现 Embedding、Vector DB 或 RAG。

## Stage 03：独立 PDF 文档解析

新增本地逐页文本提取及页码元数据，不调用 LLM，不实现 RAG。
原有 Tool Calling 功能继续保留，下文的对话运行说明仍适用。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.document_processing samples/demo-company-policy.pdf
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_document_processing.py -v
```

公开样本为自行生成的虚构制度。真实企业文件放 `samples/private/`，
其解析输出放 `output/document-processing/`；二者均被 Git 忽略。
文本型 PDF 可提取文本，扫描件暂不支持 OCR。
详细记录见 [stage-03-document-parsing.md](docs/stages/stage-03-document-parsing.md)。

学习 AI 应用开发的求职作品集项目。当前阶段：LLM + 原生 Tool Calling。
只实现终端对话和 calculator，后续阶段尚未开始。

## 环境和文件

Python 3.10 或更新版本；本机使用 Python 3.10.6。

| 文件 | 职责 |
|---|---|
| app/main.py | 读取配置、终端输入、模型请求、工具执行和流程日志 |
| app/tools.py | calculator 真实函数和工具 JSON Schema |
| tests/test_tools.py | 离线四则运算、参数错误和除零测试 |
| tests/test_flow.py | 用模拟响应验证调用 ID、工具结果传递、直接回答和轮次上限 |
| tests/test_live_api.py | 三项真实 LLM 验收，缺少密钥时跳过 |
| .env | 本地密钥和 API 配置，不提交 |
| .env.example | 不含真实密钥的配置示例 |
| requirements.txt | openai、python-dotenv 两个直接依赖 |
| .gitignore | 忽略配置、虚拟环境和缓存 |

## 配置与运行

在 PowerShell 中进入项目并安装依赖：

```powershell
# 先进入克隆后的项目根目录
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

已有 .venv 无需重建；必要时可以使用已安装的 Python 创建：

```powershell
python -m venv .venv
```

在本地 .env 填写 DeepSeek 开放平台的 API Key，不要在聊天中发送密钥：

```dotenv
DEEPSEEK_API_KEY=在这里填写真实密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

openai 是客户端包名；请求发往 DeepSeek，需要 DeepSeek 密钥。
程序按项目根目录定位 .env；缺少密钥时明确报错。API 请求消耗账户额度。

运行，无需激活虚拟环境：

```powershell
.\.venv\Scripts\python.exe app/main.py
```

输入一个问题后，程序打印完整流程并退出。再次运行可以输入另一个问题。

## Tool Calling 流程

1. Python 发送用户输入、系统提示和工具 Schema。
2. tool_choice="auto" 允许 LLM 直接回答或请求工具，不强制选择 calculator。
3. 请求工具时，LLM 返回工具名、JSON 参数和调用 ID。
4. Python 校验参数并执行 calculator(a, b, operation)。
5. 保留模型的 assistant 调用消息，再添加 role="tool" 的结果消息。
6. tool_call_id 对应调用 ID，重新请求 LLM 获得最终回答。

Schema 是给模型的说明书，不是函数本身；实际执行的是 Python 函数。
operation 支持 add、subtract、multiply、divide，不使用 eval()。
计算错误也会作为工具结果返回模型。

系统提示指导模型何时计算；程序不根据用户关键词选择工具。
main.py 中的条件判断处理模型响应和工具名称；tools.py 中的条件判断执行运算。
本阶段关闭思考模式、禁用自动重试，每次请求超时 60 秒，总计最多 4 轮请求。

## 验收

离线工具测试，不消耗 API 额度：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_tools.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_flow.py -v
```

配置密钥后执行真实 API 测试，会消耗 API 额度：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_live_api.py -v
```

| 输入 | 预期工具行为 | Python 结果 |
|---|---|---|
| 帮我计算 123 * 456 | calculator，multiply | 56088 |
| 帮我计算 999 + 888 | calculator，add | 1887 |
| 你好，请介绍一下你自己。 | 无工具，直接回答 | 不执行工具 |

日志依次展示 User Input、Tool Call Requested、Tool Name、Tool Arguments、
Python Tool Result、Final Answer；有工具调用时显示调用 ID 和请求轮次。
无工具时不打印工具名称、参数和 Python 结果。

测试检查真实响应中的工具请求、参数、Python 结果以及最终回答。
最终答案正确本身不能证明调用过工具。缺少密钥的 skipped 不代表真实测试通过。

入口判断 if __name__ == "__main__" 保证直接运行文件时才启动终端输入。

参考：[DeepSeek 接入说明](https://api-docs.deepseek.com/)、
[Tool Calling](https://api-docs.deepseek.com/guides/tool_calls/)。

## Linux 512MiB 资源验证

已实际构建前后端容器并验证公开 Demo 冷启动、六次真实请求、SSE 来源展示与知识库重建。没有 OOM，但运行峰值为 499.89MiB（512MiB 的 97.6%），目前不推荐直接采用 Render Free；没有执行外部部署。

详见 [验证报告](docs/stages/stage-16-512mb-validation.md)。`BOOTSTRAP_DEMO_KNOWLEDGE_BASE=true` 可在启动时复用 ingestion 初始化两份固定公开 PDF；默认关闭，不导入私有文件。API Key 仅通过后端运行时环境提供。

后续 **1GiB Linux 验证**完成了 11 次真实请求、SSE、多轮和删库恢复；两轮测试实际观察最高内存 659.41MiB，余量 364.59MiB。建议作为低并发作品集 Demo 的起始配置，详见 [1GiB 验证报告](docs/stages/stage-16-1g-validation.md)。没有外部部署。
