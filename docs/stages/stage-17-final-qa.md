# Stage 17：Final QA / 最终项目验收

验收日期：2026-09-20。本报告依据实际执行结果；评测原始 JSON/Markdown 留在被 Git 忽略的 `evaluation/reports/`，不把它们伪装成仓库内可点击的文件。结论仅针对本地代码、真实 API 调用和 Linux Docker 容器，不代表 Railway/Render 公开域名已经上线。

## 1. 项目版本

- Git 分支：`main`；验收时的产品代码基线提交：`65ccef36bc8d711415054b7e510b88b91fc07939`（`chore: add Railway deployment configuration`）。本阶段仅修改文档、创建本报告；最终 QA 提交以 Git 历史为准。
- 后端：Python 3.10.6；容器：Python 3.11；Docker Client/Server：29.8.0。前端：React + TypeScript + Vite。
- 检查范围：`app/` 全部模块、`frontend/` 页面/API/浏览器测试、`evaluation/`、`tests/`、公开 PDF、Docker/Compose、环境模板、README 和 `docs/stages/`。没有新增产品功能或依赖。

## 2. Backend Tests

- `python -m unittest discover -s tests -v`：**109 通过，0 失败**。覆盖 FastAPI `/health`、`/chat`、`/chat/stream`、请求校验、HTTP/SSE 错误、60 秒 LLM timeout 配置、生产限流与 429、工具参数错误、Agent 迭代上限、PDF/数据库故障、会话、来源和流式中断。
- 本机真实 HTTP 验收：生产容器 `/health`、普通聊天、calculator、知识检索、资料不足、连续三轮和 SSE 均通过。Compose 代理下的非法请求返回 422。
- `pip check`：无依赖冲突。测试环境默认 npm 缓存不可访问；改用被 Git 忽略的 `tmp/npm-cache` 后 `npm ci` 成功，这不是项目代码故障。

## 3. Frontend

- `npm ci` 成功；`npm run build` 同时完成 TypeScript 检查和 Vite 生产构建。
- `npm run test:e2e`：13 项中 **11 通过、2 按条件跳过、0 失败**。随后以 `VITE_ALLOW_DOCUMENT_UPLOAD=false` 单独执行公开 Demo 测试，**1 通过**；原先跳过的另一项专属 512MB 容器测试属于阶段 16 资源场景。
- 浏览器测试覆盖 Chat UI、loading、API 网络/HTTP/JSON/schema/timeout 错误、Sources、SSE 增量/异常、session 连续追问、手机布局及公开模式隐藏上传入口。`frontend/src/api.ts` 从 `VITE_API_URL` 读取后端地址；生产环境必须在前端构建时设置它，密钥不进入 `VITE_*`。
- 前端 Docker 镜像亦实际构建成功。前端构建目录中 3 个文件与本地真实 DeepSeek Key 精确比对，命中 **0**。

## 4. RAG

- `evaluation.run --mode retrieval` 实际对两份公开虚构 PDF 执行解析、按页切块（评测配置 80 字符/20 重叠）、本地 ONNX embedding、临时 Qdrant 入库与 Top-3 检索；14/14 需要检索的案例执行完成，至少命中一个预期来源 11/11，覆盖全部预期来源及原文证据各 **10/11**。
- `samples/verify_rag.py` 真实调用独立 RAG 模块，文档内事实、无依据拒答及跨页综合回答断言通过。Agent 评测中有依据的答案检查 **11/11**，citation 完整性 **11/11**，不存在资料时的拒答 **3/3**。
- 生产 Docker API 对“员工出差返回后多少个工作日内提交报销材料？”返回“十/10 个工作日”及 `demo-company-policy.pdf` 第 2 页；来源来自实际检索 metadata。会话中的普通聊天与 calculator 没有虚假文档来源。
- 临时生产容器不挂载卷：首次启动从两份公开 PDF 建库，删除整个容器后重新启动，知识库再次自动恢复并通过相同来源查询。

## 5. Agent

- 真实 DeepSeek 评测：工具选择 **19/19**；普通聊天 `H01/H02` 无工具，数学 `C01–C03` 使用 `calculator`，企业问题先使用 `search_knowledge_base`，混合案例 `X01` 使用两个工具。Calculator 的 Python 结果与回答数值各 **4/4**。
- 真实 API 的 `tool_calls` 记录包含工具名、参数和 Python 结果；知识工具结果返回模型后生成最终回答。`M02` 中 Agent 自主进行了 3 次知识检索，取到全部所需证据并引用三个来源。
- 单轮最多 8 个工具、最多 4 次 LLM 调用，并有 LangGraph recursion limit；达到上限和错误参数的分支由单元测试验证，不会无界循环。
- 生产 SSE 实测出现 `session → tool_start → tool_end → delta → done`；异常 SSE 的终止和前端 loading 清理由后端/浏览器测试验证。

## 6. Evaluation

- 数据集 **19 条**：知识 8、多 chunk 2、无依据 3、calculator 3、普通聊天 2、混合工具 1。运行命令分别为 `python -m evaluation.run --mode retrieval --output evaluation/reports/stage17-retrieval` 和 `--mode agent --output evaluation/reports/stage17-agent`。
- 直接检索：**18 条通过、1 条失败（M02）**；Agent：**18 条通过、1 条失败（同一 M02 的直接检索附加检查）**。失败时脚本按设计以退出码 1 结束，报告仍写入本地；不能把它写成 19/19 全通过。
- Agent 完成 19/19、工具选择 19/19、Agent 检索来源覆盖 11/11、答案依据规则 11/11、citation 11/11、拒答 3/3。默认 Top-3 的独立检索在 `M02` 漏掉工作时间证据，覆盖全部证据为 **10/11**；Agent 本身通过多次检索补齐。
- 指标是公开小数据集上的确定性规则，不是所有回答事实正确性的绝对证明；LLM 输出会有波动。评测独立使用临时库，不修改服务知识库。

## 7. Docker

- 后端生产 `Dockerfile` 构建成功；前端生产 `frontend/Dockerfile` 构建成功；`docker compose build` 成功。构建使用了部分本地缓存层，因此不是对全新网络环境的无缓存安装证明。
- 无挂载卷生产后端容器两次冷启动均完成 Demo 建库并返回 `/health`；首轮真实 `/chat` 普通问候、calculator、RAG/citation、拒答、连续三轮及 SSE 均通过；删除容器后的新实例再次通过知识查询。
- `docker compose up -d --wait` 使前后端均达到 healthy。`samples/verify_docker.py` 通过前端、`/api/health`、非法请求、真实计算、公开 PDF 上传入库及 SSE 知识回答。验收后执行 `docker compose down`，没有使用 `-v` 删除现有卷。
- `app.server` 读取 `PORT` 并监听 `0.0.0.0`；后端镜像仅复制应用代码、锁文件和两份公开 PDF。生产公开模式关闭上传，Compose 本地模式保留上传测试能力。

## 8. Security

- 检查 `.gitignore`、两个 `.dockerignore`、环境模板、Git 跟踪文件和 **全部 2 个历史提交**：212 个文本条目中，本地真实 `DEEPSEEK_API_KEY` 精确命中 **0**，常见密钥签名命中 **0**；`.env`、`.venv/`、缓存、向量库、私有文档、评测输出等禁止路径的历史跟踪数 **0**。两份已提交 PDF 是仓库生成的虚构公开样例。
- `app.reliability.log_event()` 对日志字段使用白名单，只记录事件、状态、耗时、调用次数和异常类型；测试验证密钥、完整文档、参数和异常正文不会进日志。Dockerfile/前端构建均不复制 `.env`，DeepSeek Key 只作为后端运行时变量提供。
- 代码扫描未发现生产代码中的 TODO/FIXME、debugger、本机 Windows 绝对路径或硬编码密钥。`127.0.0.1` 仅用于本地开发默认地址、容器内部健康检查及测试脚本；公开前端须设置 `VITE_API_URL`。

## 9. Issues Found

1. 默认 Top-3 直接检索在 `M02` 多事实问题中遗漏工作时间原文，导致评测 1/19 失败；这是已记录的检索质量边界，不把它报告成全通过。
2. README 中保留过时的“只完成 Tool Calling”“Docker 未验证”描述；新克隆的 Python 安装步骤顺序不清。
3. README 和阶段 13 文档链接到被 Git 忽略的本地评测报告；本机可点开，但新克隆仓库会失效。
4. 当前受限执行环境无法读取用户全局 npm 缓存；项目内缓存重试成功。外部 Railway/Render 公开地址未提供，因此本阶段没有声称线上 Demo 可访问。

## 10. Issues Fixed

- 最小修改 `README.md`：修正 Docker 验证状态、Stage 02 历史说明、依赖描述、创建虚拟环境与安装顺序，并说明评测报告为本地生成物。
- 最小修改 `docs/stages/stage-13-evaluation.md`：把三个未跟踪报告的失效链接改为可复现的本地输出路径说明。
- npm 安装使用被忽略的 `tmp/npm-cache` 完成；未修改依赖。产品代码没有发现必须立即修复的阻断 bug，因此没有重构或新增功能。

## 11. Known Limitations

- `M02` 的默认单次 Top-3 直接检索不能保证全部事实；当前 Agent 多次检索能完成该案例。未为单一开发样本改写检索架构。
- 扫描版 PDF 没有 OCR；会话仅在单进程内存中，重启后丢失；评测样本少且模型回答有随机性。
- 尚未拿到 Railway/Render 公开 URL，不能声称 Live Demo 已上线。本次 PASS 只证明代码与本地生产容器达到作品集展示质量；简历中不要写“公开在线可用”，直到真实域名完成验收。

## 12. Final Result

**PASS**

后端 109 项核心测试、真实 RAG/Agent/citation、前端生产构建、浏览器关键流程、Docker 构建与运行、密钥检查均达到本阶段标准。评测的 `M02` 失败及线上未验收已明确保留为非阻断限制。

**项目可以进入阶段 18：GitHub Portfolio Packaging。**
