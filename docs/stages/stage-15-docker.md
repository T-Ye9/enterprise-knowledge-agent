# Stage 15：Dockerization

## 当前状态

2026-09-19：容器配置和验收脚本已创建，但阶段验收未完成。
本机 docker 命令不可用，标准 Docker Desktop 路径不存在，已安装程序记录没有 Docker/Podman，也未检测到 WSL 命令。因此无法进行实际镜像 build 或启动测试。
已经向用户请求提供现有 Docker 路径，或安装并启动 Docker Desktop（Linux containers）。环境就绪后继续真实验收，不增加下一阶段功能。
本地前端构建、脚本语法检查不等于容器运行通过。

## 结构选择

采用 Compose 两个服务，不新增独立向量数据库服务：现有 Qdrant 本地模式保持。

```text
浏览器 http://127.0.0.1:8080
  → frontend: Nginx 提供 React 静态页面
  → /api/* → backend:8000 → FastAPI → 现有 Agent / Tools / RAG
后端文档入口 http://127.0.0.1:8001/docs
向量库 → knowledge-data volume
模型缓存 → embedding-cache volume
```

Backend 使用 Python 3.11 slim、CPU ONNX 所需 libgomp1 和现有 requirements.txt，不安装开发测试依赖。使用非 root 用户和单 worker，匹配本地 Qdrant 文件锁与进程内会话方案。
Frontend 多阶段构建：Node 24 + npm ci 从 package-lock.json 安装并构建，再用 Nginx Alpine 提供 dist。最终前端镜像不包含 Node、node_modules 或源码。
容器前端使用构建时公开配置 VITE_API_URL=/api，不把 Docker 服务名 backend 暴露为浏览器 API 地址。
Nginx 将 /api/chat 转成 /chat；关闭 proxy_buffering 和代理缓存，保持 SSE 增量传输；代理读取超时为 180 秒。
这是同源部署，现有本地开发 CORS 不需要改变。没有修改产品代码。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| Dockerfile | 后端依赖、非 root 用户、单 worker 启动、healthcheck |
| .dockerignore | 后端构建上下文白名单，只允许 app 和 requirements 等必要文件 |
| compose.yaml | 两个服务、运行时配置、端口、健康依赖、持久卷；显式 ASCII project name 避免中文目录名影响 Compose |
| frontend/Dockerfile | React 多阶段构建和 Nginx 运行阶段 |
| frontend/.dockerignore | 前端上下文白名单，不包含 .env.local、node_modules、测试产物 |
| frontend/nginx.conf | 静态页面、SPA fallback、API 代理和 SSE 设置 |
| samples/verify_docker.py | 对实际运行的代理入口进行完整 HTTP 验收 |
| README.md | Docker 启动、停止、模型预热和验收说明 |

## 环境变量与数据

根目录 .env 通过 backend 的 env_file 在运行时注入。Dockerfile 没有密钥 ARG/ENV，也没有 COPY .env。
两个构建上下文采用白名单，并额外排除 .env/.env.*、私钥文件和后端字节码。源码之外的本地 PDF、向量数据、报告、模型缓存及虚拟环境不送入构建上下文。
前端只接收 /api 这个公开地址。后端 .env 中既有 DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL、DEEPSEEK_MODEL 和 CORS_ORIGINS 不改变。
Compose 默认绑定本机 127.0.0.1:8080 与 127.0.0.1:8001，避免与本地开发 5173/8000 冲突。WEB_PORT 和 BACKEND_PORT 可通过根 .env 或终端环境设置。
根 .env 文件继续不提交；.env.example 是公开模板。运行时环境变量仍可被有 Docker 管理权限的人查看，env_file 不是密钥保险箱。不要公开 docker inspect 或会展开密钥的 docker compose config 输出。

knowledge-data 挂到 /app/data/vector-db；embedding-cache 挂到 /app/.cache，保存 FastEmbed 模型及 Hugging Face 缓存。
后端镜像预建可写目录并赋给 uid 10001；新 named volume 初始化沿用目录内容和权限，此处需要实际容器测试确认。
宿主已有知识库不自动复制，避免把敏感企业文件或索引烘焙进镜像。
首次启动库为空；上传公开样例即可建库。普通 docker compose down 保留卷；down -v 会删除卷，不作为日常停止命令。
会话仍为 InMemorySaver，重启丢失；当前不增加持久会话或多副本功能。

## 启动

前提：Docker Desktop/Engine 已启动，Linux containers，Compose v2。项目根目录执行：

```powershell
# 只在没有 .env 时复制，不覆盖已经配置的密钥
Copy-Item .env.example .env
# 编辑本地 .env，填写现有 DeepSeek 配置
docker compose build
docker compose up -d --wait
docker compose ps
```

访问 http://127.0.0.1:8080 和 http://127.0.0.1:8001/docs。
Backend healthcheck 使用 Python urllib 请求本容器 /health，不需 curl；Frontend 使用 Alpine wget 检查静态主页。
前端依赖后端初始 healthy 再启动。healthcheck 只检查服务存活，不检查 key 权限或预加载 embedding。depends_on 也不提供运行期间的故障恢复。
第一次 PDF 处理要下载 embedding，可先预热，避免下载时间被浏览器 180 秒超时中断：

```powershell
docker compose exec backend python -c "from app.embeddings import Embedder; Embedder()"
```

变更 .env 后重新运行 docker compose up -d；如重建后端导致 Nginx 仍缓存旧地址，可 `docker compose restart frontend`。

## 待完成的真实验收

1. docker compose build：两个镜像真实构建成功。
2. docker compose up -d --wait / ps：两个容器 healthy。
3. 页面、/api/health 和直接后端 /health 可访问；无效请求经代理仍是 JSON 422。
4. 真实 LLM 调用 calculator，Python 结果 56088，无虚假 sources。
5. 上传公开 PDF，真实解析/切分/embedding/向量保存。
6. SSE 知识工具回答包含 731 元，来源确实对应实际 retrieved metadata 第 1 页。
7. 浏览器验证页面及增量输出；容器日志不含密钥或文档全文。
8. 重启后确认向量库可继续检索，模型缓存卷保留；会话丢失符合既有设计。
9. 不输出真实密钥，检查镜像内不存在 /app/.env，前端静态文件只使用 /api。

自动 HTTP 验收脚本（本机已有 Python 虚拟环境时）：

```powershell
.\.venv\Scripts\python.exe samples/verify_docker.py
# 可调整地址
.\.venv\Scripts\python.exe samples/verify_docker.py --url http://127.0.0.1:8080
docker compose logs --tail 50
docker compose down
```

脚本真实调用 API，并上传现有公开 web-demo-policy.pdf；不会打印用户问题或文档正文。重复运行可能检索到此前相同内容的公开副本，因此核对实际工具结果的文件名/页码，而非强求只引用最后一次上传。
脚本通过不代替浏览器及持久卷重启验证。没有 Docker 就不能运行这条验收链。

## 已执行验证

- 用 VITE_API_URL=/api 执行 npm run build：TypeScript 和 Vite 构建通过。
- python -m py_compile samples/verify_docker.py：通过。
- samples/verify_docker.py --help：正常运行。
- Docker CLI/安装路径/安装记录检查：未找到 Docker，实际构建及启动尚未执行。

## 技术参考

构建上下文与 .dockerignore：<https://docs.docker.com/compose/gettingstarted/>。
env_file、healthcheck 与健康依赖：<https://docs.docker.com/reference/compose-file/services/>。
Nginx buffering 和读取超时：<https://nginx.org/en/docs/http/ngx_http_proxy_module.html>。

Docker 就绪后补记真实结果；当前不能宣称阶段 15 已验收完成。
