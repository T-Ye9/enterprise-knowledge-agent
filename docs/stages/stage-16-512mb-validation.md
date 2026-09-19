# Stage 16：Linux 512MiB 部署资源验证

日期：2026-09-19。仅本机 Docker 验证，没有外部部署、注册账号或购买服务。

## 结论

**不推荐当前实现直接部署到 Render Free。** 功能测试通过、没有 OOM，但真实请求期间 cgroup 内存峰值 **499.89MiB / 512MiB（97.6%）**，只剩 **12.11MiB**。按照项目约定的“需要合理内存余量”，本次不能判为稳定通过。

没有为了适配免费平台替换 embedding、数据库或 Agent 架构。下一步应由用户确认更高内存方案；此报告不自动选择或部署平台。

## 环境与计量

- Docker Desktop 4.91.0，Linux/amd64，Docker Engine 29.8.0，WSL2 Linux 6.6.87.2。
- 当前生产 Dockerfile、Python 3.11、单 worker，无 reload。后端和前端独立容器，各限制 512MiB。
- `--memory 512m --memory-swap 512m`：上限 536870912 字节，不允许额外 swap。未限制 CPU，因此不代表 Render Free 的 0.1 CPU 实测。
- 不挂载任何卷；数据库、缓存只在测试容器的可丢弃文件层，不使用主机既有知识库。
- 读取 cgroup v2 的 `memory.current`、`memory.peak`、`memory.events`；另检查 Docker OOMKilled、容器状态与 healthcheck。
- memory.peak 是内核记录的生命周期峰值，比采样更可靠。采样间隔为 0.3 秒加 Docker 操作耗时，瞬时峰值可能漏采；表中启动和请求峰值采用内核值。
- 计量包含 Python、原生 ONNX 分配、容器计费的文件页缓存及 healthcheck/轻量测量进程；不是 Windows committed memory。页缓存可能可回收，因此逼近上限不等于已经 OOM。
- 数据库数量诊断与重启恢复在独立 phase；请求峰值在这些诊断之前已记录，不把额外数据库诊断进程当作 API 请求。

测试版本：fastembed 0.7.4、onnxruntime 1.30.0、qdrant-client 1.19.1、fastapi 0.141.1、langgraph 1.2.11、openai 2.54.0。requirements 目前是版本范围；后续构建可能解析不同版本，本结论限于本次镜像。

## 实测

| 项目 | 结果 |
| --- | --- |
| 不初始化知识库的基础启动 | 3.03 秒；内存峰值 152.84MiB；/health 200 |
| 第一次全新部署、无模型缓存 | 37.22 秒；初始化峰值 413.64MiB |
| 第二次全新部署、无模型缓存 | 29.81 秒；初始化峰值 394.62MiB |
| 入库后的 idle memory（第二次） | 334.19MiB |
| 连续 6 次 API 请求峰值 | **499.89MiB**；采样最高 476.14MiB |
| 6 次请求后的当前内存 | 417.82MiB |
| 删除 DB 后重启，保留模型缓存 | 4.23 秒恢复；chunk 数量重新为 3 |
| 前端容器最终当前/峰值内存 | 21.83 / 52.88MiB |
| OOM / oom_kill / memory.events.max | 均为 0；容器未因内存被杀死 |
| 最终后端/前端 healthcheck | 均为 healthy |

第一次冷启动在前端首次检查失败处停止；其初始化内存记录仍有效。第二次从全新容器完整重跑。启动最坏实测峰值为 413.64MiB。

内核 memory.peak 在第二次启动就绪时为 394.62MiB，在完成六次请求时增加到 499.89MiB。因此 499.89MiB 的新增生命周期峰值发生在运行阶段。容器重启后 cgroup 峰值重新计量，不能用较低的重启后值覆盖重启前峰值。

## 四组验证

### 1. 基础启动与前端

512MiB 下后端启动、/health 成功。生产前端镜像构建成功，首页 React root、/api/health 代理通过。真实浏览器访问页面、SSE 提问、展示 731 元及 `web-demo-policy.pdf` 第 1 页、结束 loading 均通过，无页面异常。公开上传入口隐藏；后端有效 multipart 上传请求返回 403。

前端容器内存独立统计。Render Static Site 不执行后端计算，不应把这个 Nginx 容器的内存加到后端的 512MiB 限制里。

### 2. 首次初始化

镜像独立检查确认：vector-db 目录为空、embedding 缓存不存在、.env 不存在、公开 PDF 恰好两份。

```text
container start
→ validate_deployment
→ bootstrap_demo
→ 下载 BAAI/bge-small-zh-v1.5
→ extract_pdf
→ chunk_pages
→ Embedder.embed_documents
→ VectorStore.save_chunks
→ 三个 chunks / 文件名、页码、chunk ID
→ FastAPI startup complete / Agent ready
```

新建 `app/demo_bootstrap.py`，通过 `BOOTSTRAP_DEMO_KNOWLEDGE_BASE=true` 显式启用。只加载两份固定公开 PDF，复用 `index_pdf()`。默认 false，保持原本开发启动方式。

`app/api.py` lifespan 在 yield 前执行初始化。初始化异常记录安全日志后重新抛出，服务不会带着半成品库宣称已就绪。每次启动重建两个公开来源；原有同来源替换逻辑避免重复块，并能恢复上次中途失败的初始化。不扫描私有文件、不改 Agent 节点。

### 3. 连续运行

| 输入 | 实际 Tool | 结果与来源 |
| --- | --- | --- |
| 你好，请简单介绍自己。 | 无 | 直接回答，无 sources |
| 帮我计算 123 * 456 | calculator | 56088，无 sources |
| Project Cedar 每位员工每月健康补贴是多少元？ | search_knowledge_base | 731；web-demo-policy.pdf 第 1 页 |
| 公司的报销需要哪些材料，多久提交？ | search_knowledge_base | 发票/费用说明、十个工作日；demo-company-policy.pdf 第 2 页等 |
| 公司的工作时间和报销流程分别是什么？ | search_knowledge_base 两次 | 综合工作时间和报销；demo-company-policy.pdf 第 1、2 页等 |
| 公司 CEO 的私人银行卡号是多少？只依据知识库回答。 | search_knowledge_base | 明确没有足够依据，无 sources |

六次顺序请求耗时：2.25、1.70、2.06、2.08、2.66、1.72 秒。均 HTTP 200。知识库请求实际执行 retrieval→context→LLM，覆盖 Agent 内 RAG，不另外启动一个独立模型进程来冒充正常 API 负载。

检查 response sources 全部来自真实 tool result metadata；并用实际 PDF 提取文本核对工作时间第 1 页、报销第 2 页、731 元第 1 页。真实浏览器另外验证 SSE 与 source 展示。

### 4. 重启恢复

只删除测试容器中的常量路径 `/app/data/vector-db`，然后 docker restart。不接触主机 DB。启动自动恢复三块，再提问 Cedar 补贴获得 731 和真实页码。

该重启测试保留模型缓存；前面的两次全新容器则同时丢失 DB 和模型缓存。两类测试合起来证明：只读公开 Demo 可以在没有 persistent disk 的情况下重新建立知识库，但需要能下载远程模型文件。短期会话在重启后丢失，未实现持久会话。

## 依赖与失败指标

- Vector DB：Qdrant 本地模式；测试路径 `/app/data/vector-db`。
- Embedding：**本地 CPU ONNX 模型**，512 维，不是远程 embedding API；缓存约 91MiB，其中模型约 90MiB。
- LLM：远程 DeepSeek API，后端运行时环境提供密钥，不将密钥打包进镜像或报告。
- 公开固定 Demo 不必依赖 persistent storage；真实上传企业内容若需保留，仍需持久存储。本次不开放上传。
- 内存失败项是**余量不足**，不是已发生 OOM：499.89MiB 的瞬时峰值占上限 97.6%，在少量顺序请求中已经出现。
- 现有 `search_knowledge_base()` 每次构建本地 Embedder；原生模型加载/推理是主要资源风险。没有把一次峰值包装成确定的内存泄漏，也没有证明某个特定分配是根因。
- 这不是长期压测或 Render 平台实测；不宣称未来必然 OOM，也不以“这次没有 OOM”保证稳定。建议下一版在至少 1GiB 的候选资源档位再次验证，具体平台由用户确认。

Render 官方列出 Free 为 0.1 CPU/512MB，休眠、重启与重新部署会丢失本地改动，且不能挂 persistent disk。参见 [Compute plans](https://render.com/docs/compute-plans)、[Free services](https://render.com/docs/free)。Docker 同 memory/memory-swap 限制的语义参见 [Resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)。

## 遇到的问题与处理

1. Docker 命令路径与凭据 helper 不在当前进程 PATH：只设置本次测试进程 PATH。
2. Docker Hub auth 请求超时：从 AWS ECR Public 的 Docker Official Images 下载同类官方基础镜像并本地打原标签，未修改默认 Dockerfile、全局镜像源或注册 AWS 账号。
3. Docker --env-file 未提供有效密钥、启动配置校验退出：OOMKilled=false、退出码 3。验证脚本改为复用 `read_configuration()` 并以 `docker -e DEEPSEEK_API_KEY` 按名称继承进程环境；密钥值不出现在命令参数或磁盘临时文件。
4. 前端首次首页断言失败，随后页面正常：用有超时的就绪轮询替代固定睡眠，并全新容器重跑。没有确认其一定是启动竞争，因此不修改 UI 或 Nginx。
5. 浏览器断言发送按钮可用失败：输入已清空，按钮正确被禁用；填入下一轮文本后验证可用，只修测试。

## 文件与复跑

- app/demo_bootstrap.py：固定公开 Demo 初始化。
- app/api.py：启动阶段调用初始化。
- tests/test_demo_bootstrap.py：关闭开关、固定来源、失败中止与资源释放。
- samples/validate_memory.py：512MiB 容器、内存观察、六次真实请求及恢复。
- frontend/e2e/memory.spec.ts：真实只读容器的浏览器 SSE 验收。
- .env.production.example：可选初始化开关。
- output/deployment-validation/report.json：完整第二轮结果、路径、sources 和内存样本；first-cold-start.json：第一轮冷启动记录。只含公开样例。

先构建镜像，再在 Docker 可用且配置了运行时密钥的终端执行：

```powershell
docker build -t knowledge-agent-memory:backend .
docker build -t knowledge-agent-memory:frontend --build-arg VITE_ALLOW_DOCUMENT_UPLOAD=false frontend
.\.venv\Scripts\python.exe samples/validate_memory.py
```

脚本使用固定测试名称 `eka-memory-validation-*` 和本机端口 18001/18086，避免覆盖原应用；同名资源存在时拒绝继续。测试结束保留容器证据；本轮报告完成后停止两个测试容器，未删除它们。复跑前仅清理确认属于该脚本的测试容器和网络。

浏览器（frontend 目录）：

```powershell
$env:E2E_BASE_URL='http://127.0.0.1:18086'
$env:E2E_MEMORY='1'
npm run test:e2e -- memory.spec.ts
```

回归测试：108 项全部通过，其中三项真实 LLM 测试；浏览器真实 SSE 测试 1 项通过。资源脚本的 passed 表示功能断言通过，**不表示 512MiB 有足够部署余量**。
