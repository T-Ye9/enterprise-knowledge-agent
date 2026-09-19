# 阶段 11：React Web UI

## 目标与完成范围

让访问者直接聊天、上传 PDF、查看回答与来源，并在同一会话中追问。
没有登录、用户系统、支付、管理后台或新的 Agent/RAG 框架。
用普通 CSS 实现清晰的桌面和手机布局，回答以保留换行的纯文本显示，不执行模型输出的 HTML。
不引入 Markdown 依赖，因此模型的 Markdown 标记可能以原文本显示。

## 技术选择

React + TypeScript + Vite。现有 Node.js 24.19.0 符合 Vite 要求。
Vite 负责开发服务和生产打包，TypeScript 检查前端数据类型；UI 仅使用 React hooks 和 CSS。
HTTP 使用浏览器 fetch，不增加 axios 或复杂状态管理。
package-lock.json 固定实际依赖树，使用 npm ci 重现安装。

本次实际版本：React/React DOM 19.3.0、Vite 8.3.0、TypeScript 7.0.2、
@vitejs/plugin-react 6.1.1、@playwright/test 1.63.0。
后端新增 python-multipart 0.0.32，用于 FastAPI multipart/form-data 文件接收。

官方参考：[Vite 指南](https://vite.dev/guide/)、[FastAPI 文件上传](https://fastapi.tiangolo.com/tutorial/request-files/)、[FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)。

## 文件职责

| 创建/修改 | 文件 | 职责 |
| --- | --- | --- |
| 创建 | frontend/package.json | 开发、构建、验收命令和依赖 |
| 生成 | frontend/package-lock.json | 锁定实际依赖版本 |
| 创建 | frontend/index.html | 页面入口、语言和 viewport |
| 创建 | frontend/tsconfig.json | 严格检查 src 下的 TypeScript |
| 创建 | frontend/vite.config.ts | React 插件配置 |
| 创建 | frontend/.env.example | API 地址模板，无密钥 |
| 创建 | frontend/src/main.tsx | 挂载 React 根组件和 CSS |
| 创建 | frontend/src/api.ts | 类型、API 地址、fetch、超时和错误处理 |
| 创建 | frontend/src/App.tsx | 聊天记录、输入、来源、会话、上传和状态 |
| 创建 | frontend/src/styles.css | 桌面/手机布局、焦点和 loading 样式 |
| 创建 | frontend/playwright.config.ts | 浏览器、地址、超时、串行验收和报告 |
| 创建 | frontend/e2e/chat.spec.ts | 真实完整流程、模拟 API 错误、手机布局 |
| 创建 | app/document_upload.py | 文件校验、唯一命名、临时文件和已有 ingestion 委托 |
| 修改 | app/api.py | CORS 和 POST /documents；原有接口继续可用 |
| 创建 | tests/test_document_upload.py | 上传校验、清理、管线复用和 CORS 六项测试 |
| 创建 | samples/create_web_demo_pdf.py | 生成公开虚构的中文验收 PDF |
| 生成 | samples/web-demo-policy.pdf | Project Cedar 测试制度，1 页 |
| 生成 | samples/web_ui_examples.json | 浏览器真实 API 记录，含上传来源、三轮及新会话 |
| 修改 | requirements.txt | 添加 python-multipart |
| 修改 | .env.example | 添加后端 CORS_ORIGINS 模板 |
| 修改 | .gitignore | 忽略 node_modules、dist、浏览器产物及本地前端配置 |
| 修改 | README.md | 用户启动与验收入口 |
| 创建 | docs/stages/stage-11-react.md | 本文 |

浏览器截图与 JSON 测试报告写在 frontend/test-results/，该目录已忽略。
原有 app/agent.py、工具、retrieval、RAG、解析、切分和向量存储模块未修改。

## 聊天数据流与重要代码

```text
textarea 用户输入
  → App.send() 设置 busy，添加 user 消息
  → api.chat(message, sessionId)
  → POST /chat {message, session_id?}
  → 现有 Agent / checkpoint / Tool Calling
  → {answer, sources, session_id, ...原有字段}
  → App 添加 assistant 消息和来源卡片
```

`api.ts` 统一地址：

```ts
const API_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
```

首次不传 session_id，后端创建会话。成功后执行 `setSessionId(reply.session_id)`，之后每次发送带回它。
sessionId 只在当前页面内存中存在；刷新页面开启新的前端会话，后端旧历史仍保留到删除或进程退出。
“新建对话”尝试 DELETE /sessions/{id}，然后清空本地记录和 ID。
即使服务重启导致旧会话失效，也能重新开始；清理接口出错时页面显示错误。
新建对话不删除知识库内容。

`busy || uploading` 时禁用发送、上传和会话重置，避免响应归入错误的会话。
Enter 发送，Shift + Enter 换行；中文输入法 composition 期间 Enter 不触发发送。
请求超时设置为 180 秒；取消浏览器等待不等于取消后端工作，慢请求后应核对状态或新建对话。

Sources 直接使用 API 返回的真实 document/page，不让前端从模型文本推测文件名或页码。
React 将 answer 当作文本渲染，上传文件名和错误消息也不通过 dangerouslySetInnerHTML 执行。
参考来源是展示卡片，不是下载链接：本阶段不长期保留原 PDF 或实现文件下载。

## Loading 与错误

- 开始聊天设置 busy，展示“正在处理…”和 spinner，等待期间禁用发送。
- 上传展示“正在解析并入库…”，成功显示来源名、页数和片段数。
- 统一 fetch 检查 response.ok，显示 API 的字符串 detail；422 等结构化错误使用 HTTP 状态说明。
- 网络失败显示“无法连接服务”；超时显示“请求超时”。
- 聊天失败恢复输入、移除失败提问、保留前面的成功消息，便于重试，与后端失败回滚相配合。
- health 表示 API 已连接，不保证 LLM Key 有效或知识库已入库；具体问题通过 chat/upload 的错误提示呈现。

## 最小 PDF 上传接口

`POST /documents`，multipart/form-data 字段名 `file`。
成功返回 201：

```json
{"document":"web-demo-policy--唯一后缀.pdf","pages":1,"chunks_saved":1}
```

数据流：

```text
浏览器 File → FormData → FastAPI UploadFile
  → 文件大小检查
  → ingest_upload(filename, content)
  → 文件名/扩展名/PDF magic/加密/页数检查
  → 临时 PDF，使用文件名--UUID后缀.pdf
  → index_pdf(path, Embedder(), VectorStore(...), ChunkConfig())
  → Parsing → Chunking → Embedding → Qdrant
  → 关闭 store，删除临时目录
  → 返回来源、页数和 chunks_saved
```

原有 `save_chunks()` 以 source 文件名重新索引，因此唯一名称可避免同名上传覆盖其他文档。
来源卡片显示实际入库使用的唯一名称；页码与上传原 PDF 的物理页序一致。
前后端均检查非空 PDF/10 MB；后端拒绝路径、控制字符和影响引用格式的方括号文件名。
后端检查实际 PDF 内容，不仅信任 MIME 或扩展名，拒绝加密、损坏、0 页及超过 100 页的文件。
无可提取文本的扫描件由已有 index_pdf 拒绝，不新增 OCR。
文件过大返回 413，文件内容不支持返回 400，模型/向量库配置问题返回 503，缺少字段返回 422。
临时文件在成功或失败后自动清理；向量与提取正文保存在既有 data/vector-db/，该目录已忽略。
前端、会话与测试报告均不保存 API Key。本地 .env 未被修改。

上传与聊天使用同一个 CHAT_LOCK，避免 Qdrant 本地模式的并发打开冲突。
本接口是本机演示入口：没有登录/鉴权、配额或后台任务，也未实现公共网络服务级的上传治理。
10 MB 校验是应用收到文件后的限制；multipart 解析可能已将文件临时 spool 到系统目录。
首次 embedding 模型未缓存时需要下载，上传耗时可能较长。

## 地址配置和 CORS

前端 frontend/.env.local 示例：

```dotenv
VITE_API_URL=http://127.0.0.1:8000
```

后端 .env 保留现有 LLM 配置，可添加：

```dotenv
CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
```

后端载入项目根目录 .env，配置 CORSMiddleware 的明确 origin 白名单；允许 GET/POST/DELETE 和 Content-Type。
不用通配符，不启用跨域 cookie。更换前端端口须同步白名单，修改配置后重启相应服务。
前端 VITE_* 是公开的构建配置，绝不能包含 DEEPSEEK_API_KEY。
后端监听地址/端口通过 uvicorn --host / --port 配置；默认仅本机访问。
前端开发脚本使用固定 5173 和 strictPort，避免端口自动变化导致 CORS 错误。
生产预览若使用 4173，需在 CORS_ORIGINS 中明确添加该 origin。

## 如何运行

终端 1，在项目根目录：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

终端 2：

```powershell
cd frontend
npm ci
npm run dev
```

打开 http://127.0.0.1:5173；后端 /docs 仍在 http://127.0.0.1:8000/docs。
需要有效的后端 .env DeepSeek 配置。知识库为空时先上传 PDF。
使用单 worker，避免同时运行访问同一路径的其他 Qdrant 命令。
两端已运行时直接访问；要自行重启时先停止旧服务，避免端口冲突。

## 如何验证

在项目根目录：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:HF_HUB_OFFLINE='1' # embedding 已缓存时使用
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

两端服务启动后，在 frontend：

```powershell
npm run build
npm run test:e2e
```

Playwright 默认使用本机已安装的 Microsoft Edge。
没有 Edge 时可将 playwright.config.ts 的 channel 改为 chrome（需安装 Chrome），
或去掉 channel 后用 `npx playwright install chromium` 安装测试浏览器。
测试会真实上传样例、调用 DeepSeek API 并将公开样例保留在本地知识库，重复执行生成独立来源名。
它还写出 `samples/web_ui_examples.json`，仅包含虚构测试内容。

手动验收：

1. 上传 samples/web-demo-policy.pdf，看到“已入库”及 1 页/1 个片段。
2. 问“Project Cedar 每位员工每月的健康补贴是多少元？”，应得到 731 元及该上传文档第 1 页。
3. 追问“那最晚什么时候提交材料？”，应沿用同一会话，引用同一页的次月 5 日前规定。
4. 问“帮我计算 123 * 456”，应返回 56088，此条消息不显示文档来源。
5. 新建对话，再普通聊天，ID 应改变且没有来源。
6. 验证 loading 禁用发送；上传非 PDF 显示错误；服务请求失败时显示错误并保留可重试输入。

## 实际测试结果与问题定位

2026-09-18：

- 后端 67 项测试通过（新增上传/CORS 六项），包括原有三项真实 LLM 测试。
- 最终 npm run build 通过 TypeScript 检查及 Vite 生产打包。
- 前后端实际同时启动在 8000 / 5173，真实 Edge 浏览器跨域调用成功。
- 三项浏览器测试全部通过：真实上传/来源/连续三轮/新会话、模拟 502 与非法文件提示、390px 手机布局。
- 主流程用真实 PDF、embedding、Qdrant、LangGraph 和 DeepSeek；错误展示单独模拟 502，不把它算作真实 LLM 故障测试。
- 明确验证 loading 可见、等待期间按钮禁用，Sources 卡片对应实际上传 PDF 第 1 页；该 PDF 已重新解析确认正文及页码。
- 手机无横向溢出，桌面/手机截图已实际查看；真实主流程无 pageerror。

发现并处理的两项问题：

1. 首次测试无法精确定位“服务已连接”：服务正常、页面文字存在，但与说明文字共用容器。
   App.tsx 给状态文字增加独立 span，修复精确定位，未改变 API。
2. 首个验收 PDF 用英文、查询用中文。上传 201 成功，但知识回答拒答。
   Top-10 诊断确认英文块已入库，排名第 4；默认 Top-3 未召回。
   当前模型 BAAI/bge-small-zh-v1.5 主要面向中文，跨语言检索不可靠。
   将公开测试 PDF 改成中文，与当前产品语言一致，重新提取和验收全部通过。
   没有改变 Top-K、换模型或重写 RAG；真实问题仍可因检索质量导致拒答。

前端安装较慢但成功；最终 npm 安装报告 0 vulnerabilities。
既有损坏 PDF 测试的 EOF marker 提示和测试运行器颜色环境提示不影响通过结果。

## 初学者与面试知识点

1. React state 管页面当前消息、loading 和 sessionId；LangGraph checkpoint 管后端会话，两者职责不同。
2. JSON 适合 chat；FormData 适合文件上传。上传时不要手动写 Content-Type，否则缺少 multipart boundary。
3. TypeScript 类型用于开发期检查；真正的请求校验仍由后端 Pydantic 与文件校验完成。
4. CORS 根据 origin（协议、主机、端口）决定浏览器跨域访问，不能代替身份认证。
5. UI 来源来自结构化 API，而不是从 LLM 文字编造来源。
6. 上传 201 表示 ingestion 完成；它不能保证每个问题都能检索到正确片段。
7. fetch 对 502 不会自动抛错，必须检查 response.ok；网络失败与 HTTP 错误分别处理。
8. 文档索引和会话清空是独立概念；新建对话不应删除企业知识库。

阶段 11 完成，停止后续开发。
