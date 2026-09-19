# Stage 16：Deployment Readiness

## 范围与状态

完成与平台无关的代码准备及本机验证，部署方案尚未选择。没有注册账号、创建云资源、购买、推送仓库或执行外部部署。
阶段 16 初次检查时 Docker 不可用。2026-09-19 用户完成环境配置后，已实际构建前后端镜像并完成 Linux 512MiB 只读 Demo 验证；结果见 [资源验证报告](stage-16-512mb-validation.md)。功能通过，但请求峰值 499.89MiB，暂不推荐 Render Free。持久卷、限流边界未在本次资源验证中独立验收。
本文中的部署步骤是用户确认路线后可执行的操作说明，本阶段未执行。

## 现状检查

| 检查项 | 实际情况和部署要求 |
| --- | --- |
| Frontend | React/TypeScript/Vite；npm ci、npm run build；产物 frontend/dist。VITE_* 是构建时公开配置，改变量后需重新构建 |
| Backend | FastAPI + 原生 LLM + LangGraph；app.server 绑定 0.0.0.0，读取 PORT，单 worker，无 reload |
| Vector storage | 本地 Qdrant，保存向量、chunk 正文和 metadata；用户上传数据需持久磁盘，固定公开 Demo 可启用启动重建 |
| Uploaded documents | 临时原 PDF 在处理后删除；提取的企业正文和 metadata 仍留在知识库。库由全部会话共享，不具备用户隔离 |
| API Key | 只在后端运行时提供；镜像不含 .env；VITE_* 不放密钥；不公开 config/inspect 输出 |
| Persistent storage | 用户知识库需持久化 KNOWLEDGE_DB_PATH；BOOTSTRAP_DEMO_KNOWLEDGE_BASE=true 可重建固定公开样例，模型缓存也可重新下载；可另设置 HF_HOME |
| Conversation | InMemorySaver，仅单进程短期状态；重启丢失，不支持多副本会话一致性 |
| CORS | 同源 /api 可设空；前后端分离时准确 HTTPS origin；CORS 不是认证或费用控制 |
| Ports | Compose 内部 backend 8000/frontend 80；宿主默认 8001/8080，仅 localhost；PaaS 后端读取平台 PORT |
| Health | /health 只表示存活；生产启动校验配置/目录可写。没有自动检查供应商权限、模型加载或知识库内容 |
| Production commands | Backend python -m app.server；Frontend npm ci && npm run build，静态托管或现有 Nginx；单 worker，不运行 Vite dev 作为公网服务 |

目前适合低访问量的单实例作品集 Demo，不建议部署为自动扩容的 serverless 函数：模型加载、本地 Qdrant 文件锁和进程内会话需要稳定运行环境。
本地数据、私有 PDF 不自动同步到公开部署。公开资料应事先确认可发布；日志不输出敏感正文，但 LLM 请求仍会把检索片段发送给配置的供应商。

## 方案比较（2026-09-19 查证）

| 方案 | Docker | 持久存储 | 环境变量 | 免费/低成本可行性 | 复杂度 |
| --- | --- | --- | --- | --- | --- |
| Linux VPS + Compose（已有服务器，或之后评估云主机） | 直接复用两个容器和 Compose | 现有两个 named volumes，备份到受控存储 | 服务器本地运行时 .env | 已有合适主机可复用；新租主机非免费，另计流量/备份/域名等 | 中等：自己处理 HTTPS、更新、监控及备份 |
| Render 后端 Docker + 静态前端 | 后端支持 Docker；前端无须容器 | 后端付费服务附加 Persistent Disk；仅挂载路径下的数据保留 | 平台后端变量；前端构建变量 | 静态站可免费；免费后端无持久盘且会休眠，不能作为当前持久知识库的长期方案 | 较低：平台 HTTPS/构建较便利，仍需存储路径、RAM 和 CORS 配置 |
| Railway Docker 后端 + 前端服务/静态托管 | 支持 Dockerfile 服务；不是直接执行本地 Compose | Volume；一个卷可将数据库和缓存放到不同子目录 | 平台 Variables，前端构建公开 URL | 当前 Free 每月 $1 额度；Trial 一次 $5；Hobby $5/月含 $5 用量，超额另计。免费/试用卷 0.5 GB，不能承诺长期免费 | 较低至中等：需核算 RAM、卷权限和服务网络 |

Render 限制与支持来自 [免费服务说明](https://render.com/docs/free)、[Persistent Disks](https://render.com/docs/disks)、[Docker/服务支持](https://render.com/docs/faq)。
Railway 来自 [Pricing Plans](https://docs.railway.com/pricing/plans)、[Volumes](https://docs.railway.com/volumes/reference)、[Deployments](https://docs.railway.com/deployments/reference)。费用与额度会变化，选择前再核对；LLM 供应商调用费用独立于托管账单。

VPS 更容易原样复用当前 Compose，代价是运维。Render 适合希望少做运维且接受持久盘付费的情况。Railway 可试验，但免费 RAM/存储不应未经测量就认为够用。
这些是对当前架构的判断，不是已测出的平台性能。没有选择平台，也没有建立具体付费资源。用户选择后才制作该平台的最终部署配置。

## 通用代码修改

| 文件 | 职责 |
| --- | --- |
| app/deployment.py（新增） | production 模式、上传开关、CORS、可配置存储路径与启动检查 |
| app/server.py（新增） | 平台 PORT 校验、0.0.0.0、单 worker 生产入口 |
| app/llm_client.py | 提取只验证配置的 read_configuration()，避免启动校验发真实 LLM 请求 |
| app/api.py | lifespan 校验；上传关闭返回 403；message 最多 4000 字符 |
| app/embeddings.py / app/knowledge_base.py | 缓存和 Qdrant 目录从环境变量读取，原默认路径保留 |
| Dockerfile / .dockerignore | 使用新生产入口，healthcheck 读取 PORT；仅额外打包两份已公开样例 PDF |
| frontend/Dockerfile / compose.yaml | VITE_API_URL 和 VITE_ALLOW_DOCUMENT_UPLOAD 构建配置，只有公开变量 |
| frontend/nginx.conf | API 入口每 IP 10 次/分钟、burst 5、最多 2 个连接，超限 429；SSE 缓冲仍关闭 |
| frontend/src/App.tsx | 上传关闭时隐藏入口、显示公开文档说明；聊天与 sources 保留 |
| .env.production.example（新增） | 无真实密钥的生产模板 |
| .env.example / frontend/.env.example | 本地开发默认模式与前端开关说明 |
| .gitignore | 忽略 .env.*，公开模板例外；忽略 data/ 和 .cache/ |
| tests/test_deployment.py（新增） | 配置、目录权限、端口、上传关闭及请求长度等 10 项确定性测试 |
| frontend/e2e/deployment.spec.ts（新增） | 只读页面仍能聊天的浏览器测试 |
| frontend/e2e/stream.spec.ts | 测试服务器 Origin 跟随 E2E_BASE_URL，支持独立测试端口 |
| README.md | 生产入口、测试及限制说明 |

不改变 Agent 节点、工具选择、retrieval、RAG prompt 或 citation 逻辑，没有新增依赖。

## 生产配置

参考根目录 .env.production.example；已有本地 .env 不自动覆盖。平台变量不放进镜像，也不提交仓库。

```dotenv
APP_ENV=production
DEEPSEEK_API_KEY=在本地或平台填写实际密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
ALLOW_DOCUMENT_UPLOAD=false
VITE_ALLOW_DOCUMENT_UPLOAD=false
CORS_ORIGINS=
KNOWLEDGE_DB_PATH=/app/data/vector-db
EMBEDDING_CACHE_DIR=/app/.cache/embeddings
```

以上路径对应当前 Compose；PORT 在 Compose 保持 8000，平台可注入其他端口。
一个平台卷例如挂 /app/storage 时，改为 KNOWLEDGE_DB_PATH=/app/storage/vector-db、EMBEDDING_CACHE_DIR=/app/storage/embeddings，必要时 HF_HOME=/app/storage/huggingface。
只有真实挂载路径内的数据才持久化。启动检查能证明目录可写，不能证明它真是持久卷，必须做重启/重部署验收。
存储目录配置在模块导入时读取，修改后必须重启后端；不能期待请求期间热切换。

production 启动要求显式绝对存储路径、有效 key/model/API URL、HTTPS 供应商 API、明确 CORS。同源 CORS 可为空；跨域必须写例如 https://demo.example.com，不能带路径/末尾斜杠或通配符。
存储不可写时安全提示检查挂载和用户权限。镜像运行 uid=10001，平台卷必须允许它写入。Railway 官方记录非 root 卷权限限制；不要未经评估把镜像默认用户整体改成 root，应按选择的平台验证卷权限/运行 UID。

前端静态托管时：构建目录 frontend，命令 npm ci && npm run build，发布 dist，设置 VITE_API_URL=实际 HTTPS 后端地址、VITE_ALLOW_DOCUMENT_UPLOAD=false。
Compose 默认 VITE_API_URL=/api；这条相对路径只在有对应代理的部署中有效，不自动适用于独立静态站。
前端开关只控制入口显示，真正禁止上传由后端负责；公开 Demo 使用预置公开库。

## 预置公开知识库与备份

后端镜像只额外 COPY 两份明确的公开样例，不 COPY 整个 samples/，不带本机向量库。
在没有公开访问/没有并行请求期间，可在现有后端环境依次初始化：

```sh
python -m app.knowledge_base index /app/samples/demo-company-policy.pdf
python -m app.knowledge_base index /app/samples/web-demo-policy.pdf
```

Compose 就绪后可通过 docker compose exec backend 执行上述命令；公开服务开始接收访问前完成，不与同路径 Qdrant 请求并行。
这是复用已有 ingestion，不新增启动时自动入库，也不要求永久开放上传。
模型首次下载可能较慢，正式发布前预热并测量 CPU/RAM。可先以 2 GB 内存环境作为测量起点，但不是已证明的最低或保证容量。
索引包含正文，即使原 PDF 删除也不能把索引当作无敏感信息的数据。公开库只放公开文件。
备份时停止访问/停止写入，复制数据库目录；恢复时使用兼容模型/版本。缓存可重建，会话不备份。普通 down 不删除卷，避免 down -v。
当前 PDF 页码来源可验证，但上传原件不保留，UI 不能自动打开原件全文。

## 发布前的必要条件

- 用户确认平台、费用上限、数据公开范围，再创建资源；本阶段未执行。
- 阶段 15 完成真实 Docker build/up/health、非 root 卷权限、重启后检索和缓存验证。
- 域名或平台地址使用 HTTPS；SSE 代理不缓冲，实际公网测试增量、超时、error/EOF。
- 入口限制请求体大小、请求频率/连接数；不要只依靠 4000 字符校验或 CORS。后端 /documents 的开关发生在 multipart 解析之后，直接公网后端仍需网关限制。
- Nginx 限流只保护经过该代理的流量，独立公开的 PaaS 后端需要对应入口保护，不能绕开前端就失去限制。当前设置不是用户认证，不是每日预算硬上限。
- 配置供应商可用的费用限制/告警、平台预算告警；公开调用仍会消耗真实 LLM 额度，不能因静态前端免费就称整个 Demo 免费。
- 本地 Qdrant 保持一个实例/worker，避免滚动部署两个进程同时打开同一目录；允许维护窗口。不要复制同一 DB 到自动扩容副本。
- 短期 checkpoint 没有 TTL/容量治理，长时间公开运行需监测内存并安排受控重启；不宣称适合无上限流量。
- 先初始化公开资料、测试明确存在/不存在问题与 calculator、核对 sources；/health 成功不替代这一步。
- 配置磁盘备份/恢复流程及密钥轮换。不得公开密钥、容器配置展开输出或敏感文档。

这是当前 Demo 发布的实际边界，本阶段不加入登录、Redis、云向量库或多副本系统。

## 本机验证结果

2026-09-19：

| 验证 | 结果 |
| --- | --- |
| 后端完整回归 | 105 项通过，包含三个真实 DeepSeek 计算/聊天测试 |
| 最终部署专项 | 10 项通过，含 HTTPS wildcard 与无效 CORS 端口负例 |
| 只读前端生产构建 | TypeScript + Vite 通过 |
| 实际 production 启动 | python -m app.server，PORT=8016，启动校验通过 |
| HTTP smoke | /health 200、配置 origin 预检 200、其他 origin 预检 400、上传 403 |
| Edge 浏览器 | 只读/故障/流式共 9 项通过 |
| 外部部署、Docker、Nginx 限流、容器持久化 | 尚未执行，不能视为通过 |

首次浏览器回归有一个测试失败：临时 SSE 测试服务器固定允许 5173，本阶段使用 5174，因此浏览器 CORS 阻止读取。修正测试服务器跟随 E2E_BASE_URL 后重跑通过，没有放宽产品 CORS。
部分本机命令遇到自动审核超时，单独重试后执行成功；没有购买或外部权限变更。
只读页面测试用模拟流验证 UI 行为，不包装成真实公网模型验证；真实供应商调用另由后端回归覆盖。

项目根目录验证：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_deployment.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# 先设置实际生产变量，再启动；不使用 --reload 或多 worker
.\.venv\Scripts\python.exe -m app.server
```

只读前端浏览器测试需要先启动独立配置的本地前端：

```powershell
# frontend，终端 1
$env:VITE_ALLOW_DOCUMENT_UPLOAD='false'
npm exec vite -- --host 127.0.0.1 --port 5174 --strictPort
# frontend，终端 2
$env:E2E_BASE_URL='http://127.0.0.1:5174'
$env:E2E_READONLY='1'
npm run test:e2e -- e2e/deployment.spec.ts e2e/reliability.spec.ts e2e/stream.spec.ts
```

若只读后端 production，则仍按实际前端 HTTPS origin 配置；上述 UI 故障测试通过自己的路由模拟响应，不等于开启本地 HTTP origin 的生产 CORS。

阶段 16 到此停止；平台选择及真实外部部署需后续用户确认。
