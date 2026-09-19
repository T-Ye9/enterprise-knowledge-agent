# Stage 13：RAG / Agent Evaluation

本阶段只增加评测，不增加用户功能，不修改 app/、React、现有 Tool Calling 或 RAG。没有新增依赖，没有使用 LLM-as-a-judge。

## 文件与职责

| 文件 | 职责 |
| --- | --- |
| evaluation/dataset.json | 19 个问题、预期工具、真实来源页、原文证据、答案规则和计算结果 |
| evaluation/metrics.py | 确定性评分、适用案例分母、延迟统计；当前 scorer version 为 2 |
| evaluation/run.py | 验证数据集、隔离入库、运行检索/Agent、重新评分、生成报告 |
| evaluation/__init__.py | 将 evaluation 声明为 Python 模块目录 |
| evaluation/reports/*.json | 原始问题、检索块、metadata、工具参数与结果、回答、路径、耗时、版本及 SHA256 |
| evaluation/reports/*.md | 可阅读的指标和逐条结果 |
| tests/test_evaluation.py | 评分正反例、来源和证据区别、错误分层、重评一致性测试 |
| README.md | 运行入口和当前结果摘要 |

## 数据集

使用已有公开虚构 PDF：samples/demo-company-policy.pdf（2 页）及 samples/web-demo-policy.pdf（1 页）。不使用企业敏感文件，也不读取用户上传的文档。

| ID | 数量 | 内容 |
| --- | --- | --- |
| K01–K08 | 8 | 工作日、工作时间、休假申请、报销期限/材料/批准人、Cedar 补贴/提交日期 |
| M01–M02 | 2 | 跨页、跨文档和多个 chunk 的综合问题 |
| U01–U03 | 3 | 文档没有提供的年终奖、实习生年假、医保比例 |
| C01–C03 | 3 | 乘法、加法、减法 |
| H01–H02 | 2 | 普通聊天，无工具和虚假来源 |
| X01 | 1 | 查询补贴，再计算三人的总额，需要两个工具 |

X01 明确要求使用 calculator，因此只证明这个带提示的混合工具案例成功，不能推广为所有自然问题的自动规划能力。

每次运行 load_dataset() 都从实际 PDF 检查 gold quote 是否出现在指定物理页，并检查案例 ID。报告记录数据集和 PDF 的 SHA256；文件变更后不能把旧记录当作同一基线重评。
预期答案、gold 来源和评分规则不发送给 Agent，Agent 只收到问题及真实检索结果。

## 数据流与隔离

```text
公开 PDF → extract_pdf / chunk_pages → index_pdf → 临时 Qdrant
问题 → search_query → Top-K chunks → 直接检索评分
问题 → run_agent → 真实 LLM → 真实工具 → 回答/来源 → Agent 评分
原始记录 → score_case → summarize → JSON + Markdown
```

run() 复用现有 Embedder、VectorStore、index_pdf、search_query 和 run_agent，没有复制 ingestion 或向量库实现。
TemporaryDirectory 创建独立数据库，运行后清理；生产 data/vector-db 不改动。
评测进程内部通过 `patch("app.knowledge_base.DATABASE_PATH", database)` 将真实知识工具指向临时库：这里只替换存储路径，不伪造 LLM、检索结果或工具结果，也不影响其他服务进程。
直接检索结束后关闭 VectorStore，再运行 Agent，避免本地 Qdrant 文件锁冲突。

评测配置为字符 chunk size=80、overlap=20、Top-K=3；两个 PDF 共生成 5 个 chunk。
这是为了在短测试文档上观察多个 chunk，不改变产品默认的 500/50。
`--top-k` 只调整直接检索基线；Agent 工具参数仍由 LLM 按现有 schema 生成，实际值保存在 trace 中。
每个 Agent 案例是独立单轮，不连接会话 checkpoint；本阶段没有评测多轮记忆、HTTP、React 或 Streaming 首字延迟。

## 可解释指标

所有指标是通过数/适用案例数，N/A 不计分母。分母不同，不能把每个百分比直接求平均当总分。

| 指标 | 判定方法 |
| --- | --- |
| retrieval_completed | 检索成功返回，没有检索异常 |
| retrieval_source_hit | 至少一个预期文件/页出现在直接 Top-K |
| retrieval_all_sources | 所有预期文件/页都出现 |
| retrieval_evidence_coverage | 所有 gold 原文片段都出现在对应来源的检索块中 |
| tool_selection | 实际调用的工具名称集合等于预期集合；普通聊天为空集合 |
| agent_completed | 有非空回答且 Agent 没有异常，只证明完成，不证明正确 |
| agent_all_sources_retrieved | Agent 的实际知识工具结果覆盖预期来源 |
| citation_integrity | 回答的 chunk 标记和返回来源可追溯到真实工具结果，来源没有重复 |
| answer_evidence_check | 预声明答案规则匹配，gold 证据在实际引用的 chunk 中，预期来源也被引用 |
| multi_chunk_count | 实际检索的不同 chunk 数量达到案例要求；数量本身不证明使用了全部证据 |
| calculator_result / calculator_answer | 实际 Python 结果等于预期，回答包含预期数值 |
| no_document_sources | 纯计算与聊天返回空来源 |
| unsupported_refusal | 包含既有“没有足够依据”拒答语，回答中的规则可识别数量有实际引用证据 |

关键区别：命中正确页，不代表命中该页上的正确事实；有真实 citation，也不代表每一句回答都由该 citation 支持。
metrics.py 的 fact_covered() 同时核对来源和原文；score_case() 对答案进一步检查实际引用的块，而不是只检查“关键词出现过”。
Agent 异常时 Agent 指标失败，但不抹掉已经独立获得的检索结果。检索异常则检索指标失败。

延迟由 time.perf_counter() 测量。分别记录单条直接检索和完整 Agent 时间；初始化及入库单独记录。
p50 是中位数，p95 使用 nearest-rank。19 条样本的 p95 就是最大值，不能当作大规模服务的稳定尾延迟。

## 运行

在项目根目录执行，无需启动前后端：

```powershell
.\.venv\Scripts\python.exe -m evaluation.run --mode retrieval --output evaluation/reports/my-retrieval
.\.venv\Scripts\python.exe -m evaluation.run --mode agent --output evaluation/reports/my-agent
.\.venv\Scripts\python.exe -m evaluation.run --mode replay --input evaluation/reports/agent.json --output evaluation/reports/my-replay
.\.venv\Scripts\python.exe -m unittest tests.test_evaluation -v
```

retrieval 使用真实本地 embedding，无 LLM 调用；首次需要下载模型，已缓存时可设置 `HF_HUB_OFFLINE=1`。
agent 使用现有 .env 中的 DeepSeek 配置，会真实调用 API。密钥不写进数据集、State 或报告。
replay 不重新检索或调用 LLM，只对保存的原始结果应用当前评分器；其延迟是原始运行耗时。
输出参数是不含扩展名的路径，同时生成 .json 和 .md。质量检查存在失败时退出码为 1，报告仍完整生成；全部适用检查通过才返回 0。

## 实际结果（2026-09-18）

真实运行环境：Python 3.10.6，openai 2.54.0，langgraph 1.2.11，fastembed 0.7.4，qdrant-client 1.19.1，pypdf 6.19.0。
Embedding 为 BAAI/bge-small-zh-v1.5（512 维），LLM 为 deepseek-flash。

当时生成的本地报告 `evaluation/reports/agent-rescored.md` 对同一批 19 条真实 Agent 记录使用评分器 v2 重新评分，没有重跑模型来挑选更好的回答。`evaluation/reports/` 被 Git 忽略，克隆仓库后须自行运行评测生成报告。

| 检查 | 结果 |
| --- | --- |
| 直接检索完成 | 14/14 |
| 直接检索至少命中一个来源 | 11/11 |
| 直接检索全部来源 / 全部证据 | 各 10/11 |
| Agent 完成 / 工具选择 | 各 19/19 |
| Agent 来源覆盖 / 引用核对 / 答案依据规则 | 各 11/11 |
| 多 chunk 数量 | 2/2 |
| Calculator 实际结果 / 回答数值 | 各 4/4 |
| 普通聊天与纯计算无文档引用 | 5/5 |
| 未支持问题拒答规则 | 3/3 |

单条直接检索 p50=0.031 秒、p95=0.054 秒（14 条）；Agent p50=1.981 秒、p95=3.703 秒（19 条）。不包含 HTTP/React；本次模型已缓存，不能代表首次启动或不同机器的性能。

### 保留的质量失败：M02

M02 同时询问工作时间、报销期限和 Cedar 补贴。直接 Top-3 检索取到两个 Cedar 块，遗漏工作时间证据，因此最终报告仍有失败，脚本返回 1。
当时的本地对照报告 `evaluation/reports/retrieval-top4.md` 显示：Top-K=4 让所有页都出现，但新增的是休假片段，仍没有工作时间证据，证据覆盖依旧 10/11。不能因为页码覆盖提高就宣称问题已解决。
同一案例中真实 Agent 分别搜索三个主题，最终取得并引用了所需证据；这是已有 Agent 的执行表现，本阶段没有新增查询拆分功能。

### 评分器误判及修正

当时的本地初始报告 `evaluation/reports/agent.md` 的拒答检查为 0/3：评分器 v1 一律禁止未知问题回答中出现数量。
检查原始回答后发现模型确实拒答，但为了说明资料范围，引用了真实文档中的 731 元补贴。因此这是评分规则的误判，不能通过改写模型回答掩盖。
v2 允许实际引用证据中出现的数量，同时测试无依据的 5000 元、80% 和没有 citation 的数量不能通过。
原始报告保留；agent-rescored.json 标明 recorded_mode、旧/新 scorer version 和原始时间。相同原始记录重复评分结果一致，测试明确禁止 replay 调用 create_client()。

验证：完整后端回归 83 项通过；最终增加异常分层用例后，评测专用 10 项测试通过。没有修改产品代码或新增依赖。

## 局限与改进方向

这是公开的小型开发集，只有两份短 PDF，并非隐藏测试集。高命中率不能推广为真实企业文档表现。
答案检查是预声明事实的确定性代理：同义表达可能被误判失败；额外编造句、否定、错误关系、把已知金额套在未知制度上可能漏检。拒答数量规则也不能证明整个回答没有幻觉。
工具集合正确不等于每一步顺序和参数都最优；单次真实 LLM 结果也不保证下次一致。规则评分可复现，模型生成本身并非确定性。
没有使用 LLM-as-a-judge，因此结果不受另一个模型主观打分影响；未来如引入，需配合人工抽查并记录 judge 模型/提示词及分歧，不能视作绝对真值。

后续可以扩大公开文档、加入相似干扰块和隐藏问题，覆盖自然混合工具问题、同义词及跨语言检索；比较来源多样性、查询拆分和切分策略，而不是只增加 K。
对关键回答做人工逐句依据审查；重复真实运行报告成功率波动。多轮、流式首字时间、并发和 HTTP 错误应作为独立评测扩展。本阶段不实现这些改进。

## 面试知识点

- Retrieval evaluation 和 generation evaluation 分开：正确回答可能来自模型常识，不能反推检索一定正确。
- 页级来源命中与事实级证据覆盖不同；citation 可追溯也不自动证明语义忠实。
- Ground truth 必须来自实际 PDF 页码和原文，不能让被评测模型自己生成答案标准。
- 未知问题仍会检索到相似块，重点是模型是否根据证据范围拒答，而不是要求向量库返回空。
- 固定数据、配置、文件哈希和原始 trace 支持回归；重评不等于重跑系统。
- 质量失败应保留并解释；不要调评分规则或测试题只为得到 100%。

阶段 13 到此停止。
