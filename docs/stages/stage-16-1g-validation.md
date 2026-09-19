# Stage 16：Linux 1GiB 资源验证

本机 Docker 验证，2026-09-19。没有外部部署、账号注册、付费或平台配置修改。

## 结论

当前作品集公开 Demo 在 **1GiB 内存、无额外 swap** 的 Linux 后端容器中完成了冷启动、11 次顺序真实请求、SSE、三轮会话和删库重建。全程没有 OOM、内存错误或非预期重启。两次测试运行中观察到的最高内核内存峰值为 **659.41MiB / 1024MiB**，剩余 **364.59MiB（35.6%）**。完整通过的第二次运行峰值为 630.02MiB。

**建议把 1GiB 作为当前单实例、低并发 Demo 的起始资源配置。** 本轮未做并发和长期压测，不能以此保证高并发或长期运行。现在没有必须升到 2GiB 的证据；若开放上传、扩大知识库、增加并发或后续监控显示峰值接近上限，再用 2GiB 复测。

## 测试条件

- 使用当前生产 `Dockerfile` 重建后端镜像；前端沿用生产镜像。后端单 worker，CPU 不限速。前端是独立容器，不计入后端 1GiB 限额。
- Docker 限制：`--memory 1g --memory-swap 1g`，实际两项均为 **1,073,741,824 字节**，即 1GiB，不允许额外 swap。
- 新建容器只打包两份公开 PDF；镜像检查证实原始 Vector DB 为空、模型缓存不存在、没有 `.env`。不挂载任何持久卷，不读取主机既有数据库。
- `BOOTSTRAP_DEMO_KNOWLEDGE_BASE=true`；启动时复用现有 PDF parsing、chunking、FastEmbed ONNX embedding 和 Qdrant 本地入库流程。启动后库中 3 个 chunks。
- 运行时环境变量传入密钥；镜像和报告都不含 API Key。测试使用真实 DeepSeek LLM API。
- 内存读取 Linux cgroup v2 `memory.current`、`memory.peak`、`memory.events`。`memory.peak` 是内核准确的生命周期高水位；逐请求 `memory.current` 是约 0.2 秒加 Docker 命令开销的采样，可能漏掉瞬时峰值。
- CPU 取 cgroup `cpu.stat` 的 `usage_usec`，每次请求计算 CPU 秒数/实际请求秒数，结果表示**占一个 CPU 核的平均百分比**，不是瞬时 CPU 峰值。采样及 healthcheck 有小量开销。

## 资源数据

| 指标 | 实测 |
| --- | ---: |
| 从全新容器启动到 `/health` 成功 | 完整重跑 33.03 秒；首次运行 85.08 秒 |
| 知识库首次初始化阶段内存峰值 | 完整重跑 434.71MiB；首次运行 **519.53MiB** |
| 初始化后闲置内存 | 完整重跑 374.64MiB；首次运行 466.69MiB |
| 完整通过的 11 次请求最高内存 | **630.02MiB**，发生在 SSE 轮次 |
| 两次运行实际观察到的最高内存 | **659.41MiB**，第一次因测试断言中止后的 cgroup 读数 |
| 以实际最高值计算的剩余余量 | **364.59MiB / 35.6%** |
| 11 次请求后的当前内存 | 551.41MiB |
| 请求总 CPU 时间 / 总请求墙钟时间 | 5.20 / 21.45 秒，约 24.2% 的一个 CPU 核 |
| 单次请求最高平均 CPU | 40.9% 的一个 CPU 核（首次知识检索） |
| OOM / oom_kill / memory.events.max | 均为 0 |
| 非预期容器重启 | 0；运行阶段 RestartCount 为 0 |
| MemoryError / 内存相关错误日志 | 0；错误日志计数 0 |

| 请求 | 时间 | 本轮采样最高内存 | 平均 CPU/核 | 结果 |
| --- | ---: | ---: | ---: | --- |
| 普通聊天 | 2.08s | 395.56MiB | 33.8% | 不调用工具 |
| `123 * 456` | 1.66s | 397.49MiB | 9.1% | calculator → 56088 |
| Cedar 补贴 | 2.36s | 492.37MiB | 40.9% | search → 731；真实第 1 页 |
| 差旅报销材料 | 2.55s | 456.01MiB | 19.0% | RAG；真实第 2 页 |
| 工作时间 + 报销期限 | 2.11s | 480.58MiB | 36.3% | 跨页 RAG；检索两次 |
| CEO 私人银行卡号 | 2.31s | 498.95MiB | 21.7% | 明确知识库资料不足 |
| 会话第 1 轮：报销材料 | 2.48s | 488.36MiB | 18.3% | 检索并保存会话 |
| 会话第 2 轮：那多久提交 | 1.05s | 488.79MiB | 10.4% | 理解为十个工作日 |
| 会话第 3 轮：出差前做什么 | 1.44s | 488.58MiB | 12.4% | 理解为先获主管批准 |
| SSE 流式 Cedar 问答 | 2.16s | 608.12MiB | 33.3% | 增量内容、最终答案和来源 |
| `999 + 888` | 1.25s | 550.96MiB | 13.4% | calculator → 1887 |

SSE 轮次本轮采样为 608.12MiB，但内核生命周期峰值从之前的 566.34MiB 增加至 **630.02MiB**，因此最高值发生在这次请求中。`memory.current` 逐请求采样不是精确单次峰值；用较大的内核值做部署判定。资料不足回答引用了真实的公开文档片段，用来说明这些片段没有银行卡号；没有生成该号码。

首次测试运行在第 8 次多轮请求的**验收脚本断言**中止：脚本错误地要求引用只能来自本轮工具结果，而项目本就允许同一会话引用上一轮真实检索。核对 `app/citations.py` 后，只修正脚本并用**全新容器**完整重跑。首次运行记录了 85.08 秒启动、519.53MiB 初始化峰值和 466.69MiB idle。额外诊断时读取 cgroup `memory.peak=691437568` 字节，即 **659.41MiB**。首次运行的原始 JSON 随重跑被覆盖，因此上述数值来自当时保留的工具输出，而不是第二次完整 JSON；报告仍将其计入“实际观察值”，不掩盖运行间波动。第一次中止与 OOM 无关。

Source citation 对应工具返回的真实 PDF metadata。第 2、3 轮会话没有再次调用检索工具，但引用来自同一会话第一轮的真实检索；这是现有 `resolve_citations()` 的设计，不是模型自造来源。SSE 通过前端 Nginx `/api` 代理发起，包含 `delta` 和 `done` 事件、731 答案及 `web-demo-policy.pdf` 第 1 页。

## 删除数据库后的恢复

只删除本轮测试容器中的 `/app/data/vector-db`，再执行一次**计划内** Docker restart。启动至 `/health` 成功为 **4.20 秒**，知识库重新生成 3 个 chunks，随后真实检索回答 Cedar 补贴 731 元，并返回 `web-demo-policy.pdf` 第 1 页。

安全日志中 `demo_initialization_started` 和 `demo_initialization_finished` 各出现 **2 次**，证明首次启动和计划重启都执行了自动入库。Docker `RestartCount` 仍为 0；它表示自动重启次数，不把手动 `docker restart` 计入此值。重启后容器为 running/healthy，OOMKilled=false。

这证明固定公开 Demo 不依赖 persistent disk，模型缓存缺失时会从远程重新下载。若未来允许用户上传并需要长期保留企业文档，则需持久存储，不适用本次无卷结论。短期会话状态在重启后仍会丢失。

## 主要内存来源与平台判断

代码采用本地 `BAAI/bge-small-zh-v1.5` ONNX embedding，模型缓存约 **91MiB**；`search_knowledge_base()` 每次检索会创建新的 `Embedder()`，本地模型载入与推理产生显著内存峰值。Qdrant 本地数据库只有 3 个 chunks，重启后文件约 **44KiB**。对比普通聊天约 396MiB、知识检索约 492MiB 以及 SSE 约 630MiB 的采样/内核高水位，本地 embedding 与 Python/Agent 进程内存是主要资源风险。**无法从这些数据精确划分每个 Python 对象或 ONNX 分配的字节数**，也未证明内存泄漏；没有因此更换模型或重构架构。

Railway 适合当前架构作为**待用户确认的部署候选**：支持 Docker 服务、运行时环境变量和可配置资源上限；固定公开 Demo 可在临时磁盘上启动重建。Railway 官方计划表显示 Free 每服务上限 **0.5GB RAM**，不适合本项目；Trial 为 **1GB RAM**，但不是长期公开 Demo 的可靠承诺；Hobby 可配置更高的每副本上限，并按实际资源用量计费。[Railway plans](https://docs.railway.com/pricing/plans)、[Services](https://docs.railway.com/services)、[Right-size CPU and memory](https://docs.railway.com/guides/right-size-cpu-memory)。

若用户后续选择 Railway，建议起点：**Hobby、后端 1 个副本、内存上限至少 1GiB、CPU 上限 2 vCPU、无持久卷的固定公开 Demo**；仅在真实监控和并发测试需要时升级至 2GiB。2 vCPU 是允许现有两线程 ONNX 模型运行的建议上限，**本轮未设置 CPU 限速，未验证该上限下的启动与延迟**。Railway 文档使用 “GB” 计量，创建服务时还应核对平台实际按十进制 GB 还是 GiB 限制；本轮 Docker 是二进制 1GiB。API Key 必须通过运行时环境变量配置，不能写入仓库或镜像。此处没有执行 Railway 部署，也没有承诺费用为零。

## 文件和复跑

- `samples/validate_1g.py`：新建 1GiB、无 swap、无卷容器，记录 cgroup 内存/CPU，检查 11 次真实请求、SSE、多轮及恢复。
- `output/deployment-validation/report-1g.json`：完整通过的第二轮逐请求测量与公开测试回答，不含 API Key；首次中止运行的更高峰值见上文的 Docker CLI 观察值。
- 本文件：可审阅的结论与局限。

当前 `Dockerfile`、ONNX embedding、Qdrant、Agent、RAG、API 和前端代码均未修改。新增脚本通过语法检查，现有 Demo 初始化测试 3 项通过；镜像重建成功。测试容器使用 `eka-1g-validation-*` 专属名称和本机端口 18011/18096，不接触主机现有 Vector DB。验证完成后停止容器，保留原始报告。

```powershell
docker build -t knowledge-agent-memory:backend .
docker build -t knowledge-agent-memory:frontend --build-arg VITE_ALLOW_DOCUMENT_UPLOAD=false frontend
.\.venv\Scripts\python.exe samples/validate_1g.py
```

脚本要求已在本地 `.env` 配置实际 DeepSeek Key。再次执行前，只清理上次此脚本创建的容器和网络；脚本不会自行移除失败证据。
