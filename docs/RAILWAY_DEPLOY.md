# Railway 后端部署

此仓库只把 FastAPI 后端部署到 Railway；React 静态站点单独部署到 Render。当前文件是部署准备，提交它不会自动创建 Railway 服务或触发 `railway config apply`。

仓库根目录的 `Dockerfile` 会被 Railway 自动识别；镜像的 `CMD ["python", "-m", "app.server"]` 调用 `app/server.py`，读取平台提供的 `PORT` 并监听 `0.0.0.0`。启动时先检查配置并重建两份公开 PDF 的本地知识库，完成后 `/health` 返回 `{"status":"ok"}`。`.railway/railway.ts` 使用 Railway 当前推荐的 Infrastructure as Code，保存 GitHub 源、单实例、非敏感变量和 `/health`（启动等待 300 秒）。它不会保存真实密钥，也不使用已废弃的 `railway.json` / `railway.toml`。

## 必填变量

“配置位置”为 IaC 的项目会在应用配置时写入 Railway；“手动”项目须由你在 Railway 的后端服务 Variables 中填写。只有示例值和配置文件可以提交，真实密钥不可提交。

| 变量名 | 示例值 | 用途 | 配置位置 | 包含 secret？ | 实际值可提交 GitHub？ |
| --- | --- | --- | --- | --- | --- |
| `APP_ENV` | `production` | 启用生产配置检查、关闭开发默认行为 | IaC | 否 | 是 |
| `ALLOW_DOCUMENT_UPLOAD` | `false` | 关闭公开文档上传 | IaC | 否 | 是 |
| `BOOTSTRAP_DEMO_KNOWLEDGE_BASE` | `true` | 每次启动从两份公开 PDF 重建知识库 | IaC | 否 | 是 |
| `KNOWLEDGE_DB_PATH` | `/app/data/vector-db` | 容器内可写的本地向量库路径；不挂持久卷 | IaC | 否 | 是 |
| `EMBEDDING_CACHE_DIR` | `/app/.cache/embeddings` | 本地 ONNX embedding 模型缓存路径 | IaC | 否 | 是 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 地址，生产模式必须为 HTTPS | IaC | 否 | 是 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 当前调用的模型名称 | IaC | 否 | 是 |
| `DEEPSEEK_API_KEY` | `YOUR_DEEPSEEK_API_KEY` | 调用 DeepSeek；IaC 的 `preserve()` 只保留 Railway 里已有的值 | **手动** | **是** | **否** |
| `CORS_ORIGINS` | `https://your-site.onrender.com` | 允许 Render 前端浏览器访问后端；填真实 HTTPS origin，不加路径或末尾 `/` | **手动** | 否 | 是，但实际域名尚未确定时由 Railway 保存 |

`CORS_ORIGINS` 在生产模式中必须显式存在。同源部署可以设为空；本项目是 Render + Railway 分离部署，前端上线后应填 Render 实际域名。多个 origin 用英文逗号分隔，不要使用 `*`。`DEEPSEEK_API_KEY` 和 `CORS_ORIGINS` 使用 `preserve()`，所以后续运行 `railway config apply` 不会用仓库中的占位符覆盖平台上的值。

## 可选变量

这些值已有镜像默认值，**不需要在 Railway 手动填写**；只有改变默认行为时才考虑覆盖。

| 变量名 | 示例值 | 用途 | 默认来源 | 包含 secret？ | 非敏感值可提交 GitHub？ |
| --- | --- | --- | --- | --- | --- |
| `HF_HOME` | `/app/.cache/huggingface` | Hugging Face 下载缓存根目录 | `Dockerfile` | 否 | 是 |
| `PYTHONDONTWRITEBYTECODE` | `1` | 不生成 `.pyc` 文件 | `Dockerfile` | 否 | 是 |
| `PYTHONUNBUFFERED` | `1` | 及时输出服务日志 | `Dockerfile` | 否 | 是 |

`WEB_PORT`、`BACKEND_PORT` 只用于本地 Compose；`VITE_API_URL`、`VITE_ALLOW_DOCUMENT_UPLOAD` 只在 **Render 前端构建**时配置，绝不放进 Railway 后端。Render 应设置 `VITE_API_URL=https://你的Railway后端域名` 与 `VITE_ALLOW_DOCUMENT_UPLOAD=false`；`VITE_*` 会进入公开的浏览器代码，不能放密钥。

## Railway 自动提供，不需要填写

| 变量名 | 示例值 | 用途 | 包含 secret？ | 值可提交 GitHub？ |
| --- | --- | --- | --- | --- |
| `PORT` | `8080`（实际由 Railway 分配） | `app/server.py` 在此端口监听；Docker 健康检查也读取它 | 否 | 数字本身可以，但不要在配置中固定 |
| `RAILWAY_PUBLIC_DOMAIN` | `backend-abc.up.railway.app`（生成域名后才有） | 平台提供的服务域名信息；本应用不读取此变量 | 否 | 是，但域名由平台分配 |

Railway 还提供其他项目和部署元数据变量，本应用未读取。`healthcheck` 是 IaC 的服务设置，不是后端环境变量；路径为 `/health`，超时 300 秒。

## 你本人必须完成的步骤

1. 在 Railway 为此 Demo 创建**独立项目**，授权 Railway 访问 `T-Ye9/enterprise-knowledge-agent`，从 GitHub 建立名为 `backend` 的服务。检查后端可用内存**至少 1GiB**、单实例、关闭 Serverless/App Sleeping、不挂持久卷。Railway 当前 IaC 文档没有内存额度或 App Sleeping 的受支持字段，这两项仍须在服务设置中核对。
2. 在 `backend` → Variables 填真实 `DEEPSEEK_API_KEY`；拿到 Render 站点域名后填 `CORS_ORIGINS`。若先部署后端，可先把 `CORS_ORIGINS` 设为**已定义的空值**，待 Render 域名确定后更新。不要把密钥粘贴到 Git、聊天、前端变量或命令行参数里。
3. 在本机项目根目录执行 `npm ci --prefix .railway`。安装 CLI：`npm install -g @railway/cli`，然后依次执行 `railway login`、`railway link`、`railway config plan`；核对项目、环境、变更和费用后执行 `railway config apply`。若 plan 出现删除其他资源的操作，请停止，不要应用。这些命令不会由 GitHub 自动执行；`plan` 只预览，`apply` 才改变 Railway 配置。若已有服务名称不是 `backend`，先调整 `.railway/railway.ts` 中的名称以避免创建第二个服务。
4. 在 Railway 为后端生成公开 HTTPS 域名，确认构建日志使用根目录 `Dockerfile`、服务 `/health` 成功，再用该域名配置 Render 前端的 `VITE_API_URL`。如果首次部署早于变量配置，启动失败是预期结果；保存变量后重新部署即可。

仅凭仓库文件不能替你创建 Railway 项目、授予 GitHub 访问权限、设置密钥、确定 Render 域名或确认资源费用。项目尚未执行 `railway config plan/apply`，实际平台配置以你审阅的 plan 为准。

官方依据：[Railway IaC](https://docs.railway.com/infrastructure-as-code)、[IaC 参数参考](https://docs.railway.com/infrastructure-as-code/reference)、[Dockerfile 检测](https://docs.railway.com/builds/dockerfiles)、[Healthchecks 与 PORT](https://docs.railway.com/deployments/healthchecks)。
