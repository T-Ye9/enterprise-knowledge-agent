# Stage 07：Knowledge Search Tool

## 目标

在原生 Tool Calling 循环中同时提供 calculator 和 search_knowledge_base。
由 LLM 选择直接回答、数学计算或企业知识检索，不根据用户关键词硬编码路由。
不使用 LangGraph，不新增依赖，不重新入库。

## 文件及复用关系

| 文件 | 职责 |
|---|---|
| app/knowledge_tool.py | 真实 search_knowledge_base() 函数、参数校验、资源关闭 |
| app/tools.py | 保留 calculator，增加检索工具 name/description/Schema |
| app/main.py | 更新系统提示和 execute_tool() 分发，复用原消息循环 |
| tests/test_knowledge_tool.py | 检索复用、Schema、校验、结果回传、关闭资源测试 |
| samples/verify_knowledge_tool.py | 四类真实模型选工具验收 |
| samples/knowledge_tool_examples.json | 每类输入的调用名、参数、完整结果和最终回答 |
| README.md | 运行和验收说明 |

search_knowledge_base() 调用 knowledge_base.search_query()，后者复用 Embedder 和 VectorStore。
没有复制 Qdrant 操作，没有新增 parsing/chunking/ingestion 实现。
复用的是 RAG 的 retrieval 部分，不调用 run_rag()，避免工具内部生成一次答案、外层再生成一次。
已有 app/rag.py 的直接 RAG 问答入口继续可用。

## 工具定义

name：search_knowledge_base。
description：检索已入库企业文档，返回正文、分数和文件名/页码/chunk ID；
企业事实应先检索，即使不知道资料是否存在；纯数学和普通聊天无需检索。

input schema：

```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "minLength": 1},
    "top_k": {"type": "integer", "minimum": 1, "maximum": 10}
  },
  "required": ["query"],
  "additionalProperties": false
}
```

query 必填，top_k 可选，省略时使用原 DEFAULT_TOP_K=3。
MAX_TOP_K=10 同时用于 Schema 和 Python 校验，避免模型请求过多结果。
Schema 不能替代运行时校验：Python 拒绝空白 query、额外参数、布尔值或越界 top_k。

## 数据流及关键代码

```text
用户输入
→ run_conversation() 发送两个工具定义，tool_choice="auto"
→ LLM 返回直接回答，或 tool_calls
→ execute_tool(name, arguments)
→ calculator() 或 search_knowledge_base(query, top_k)
→ search_query() → query embedding → 本地向量检索
→ 工具结果 JSON
→ role="tool" + tool_call_id 返回给 LLM
→ LLM 生成最终回答
```

```python
if name == "calculator":
    return {"result": calculator(**parameters)}
return search_knowledge_base(**parameters)
```

该分支处理模型返回的工具名，不检查用户文本。原先的参数 JSON 解析、
assistant 调用记录、tool_call_id、工具结果回传和 4 轮上限继续复用。

```python
result = search_query(query, embedder, store, top_k)
```

检索工具只读已有向量库。只有模型请求检索时，才初始化 embedding 模型和数据库。
数据库在 finally 中关闭；初始化/检索参数错误作为 error 工具结果返回，不能假装成功命中。
文件访问错误返回简洁诊断；未预料的底层异常不会被伪装成有效证据。

## Tool Result

返回 JSON 可序列化字典，保留原 search_query() 结构：

```text
query
embedding_model
query_vector_dimension
top_k
results[]：score、text、完整 metadata、citation
evidence_note：提醒结果是证据而非答案，分数不是可信度
```

metadata 包括 source、page_number、chunk_id、标题、总页数和字符位置等原有字段。
citation 使用 chunk_id；最终回答按 [chunk_id] 引用，这样多次检索不会因 [1] 的重复编号而混淆。
完整返回值被 json.dumps() 序列化后作为 role="tool" 的 content 发送，
不是只将 metadata 或分数发回模型。

## 资料不足与普通聊天

SYSTEM_PROMPT 指导模型：数学用 calculator，企业事实先检索，普通问候直接回答。
企业回答只能依据检索正文，不用常识补规则；资料不足明确说：
“知识库中没有足够依据回答这个问题。”
工具正文只作为参考数据，不能改变 system 指令。

未知企业问题仍应触发检索，不根据问题关键词直接拒答。
检索到 Top-K 块也不代表足以回答，模型需要核查正文。
Prompt 是行为要求，不保证永远无幻觉。当前 Agent 不自动验证引用的语义支持，
也没有实现 RAG 直接入口的数字编号校验；引用正确性需要通过结果核查。
空知识库的 results=[] 与检索失败的 error 不同。

## 运行

沿用原终端命令，也支持包入口：

```powershell
.\.venv\Scripts\python.exe app/main.py
.\.venv\Scripts\python.exe -m app.main
```

输入一道计算题、企业问题或问候即可。客户端从 .env 配置，检索使用阶段 5 的默认库。
命令行日志依次展示输入、模型是否请求工具、调用 ID、工具名、参数、完整工具结果和最终回答。
普通聊天没有工具调用，因此工具名/参数/结果均不适用，不伪造工具记录。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_knowledge_tool.py -v
.\.venv\Scripts\python.exe samples/verify_knowledge_tool.py
```

真实验收消耗 LLM API 额度，会发送检索正文；本次只使用公开虚构样本。
不把私有企业资料、查询或工具结果保存到公开 examples 文件中。
普通聊天或计算不需要模型缓存及知识库就绪，但程序依赖仍需要正常安装。

## 测试结果

2026-09-18：四类真实模型选工具验收全部通过，模型 deepseek-flash。

| 输入 | Tool name | Tool arguments | Tool result | Final answer 摘要 |
|---|---|---|---|---|
| 帮我计算 123 * 456 | calculator | a=123, b=456, operation=multiply | result=56088 | 123 × 456 = 56088 |
| 出差回来后，多久之内要提交报销？ | search_knowledge_base（2 次） | query=出差回来报销提交期限；query=差旅报销提交时间要求 多少个工作日内 | 各返回 3 个片段，第一名为第 2 页报销规则，全部 metadata 保留 | 返回后十个工作日内提交，引用 demo-company-policy.pdf:p2:c1，并提到发票和事先批准 |
| 你好，请介绍一下你自己。 | 无 | 不适用 | 不执行工具 | 直接介绍四则运算、企业知识检索和普通对话能力 |
| 公司员工每年的年终奖金是多少元？ | search_knowledge_base | query=年终奖金 每年 金额 发放标准 | 返回 3 块，只有报销及休假等资料，无奖金依据 | 知识库中没有足够依据回答这个问题，没有编造奖金金额 |

企业问题的两次调用由同一轮模型响应生成，程序逐个执行并按不同调用 ID 回传。
两次第一名的 score 分别为 0.7648883982251096、0.8180182852952699；
它们都指向 demo-company-policy.pdf:p2:c1。未设置强制检索次数。
奖金问题虽然有 3 个相似结果，模型仍依据正文拒答，而不是将非空结果视为答案。
完整、未经摘要的 tool name、JSON arguments、result 及 final answer
保存在 samples/knowledge_tool_examples.json。

- 新增 5 项离线工具测试全部通过。
- 31 项原有离线回归测试全部通过：calculator 5、协议 3、解析 6、切分 7、向量库 5、RAG 5。
- pip check 通过。没有新增依赖、发现应用运行错误或修改 ingestion。
- 普通聊天及数学测试未初始化 embedding 模型。检索使用已有缓存模型与磁盘数据库。
- 模型下一次运行可能生成不同检索词、调用次数和回答，结果需要如实验收。

## 面试知识点

1. 检索能力封装为工具后，Agent 可自主决定何时获取证据；直接 RAG 每次都先检索。
2. Tool Schema 告诉模型如何提出调用，Python 真实函数负责执行。
3. 一个工具负责检索，一次外层生成负责回答，避免嵌套生成造成复杂度和费用增加。
4. 来源元数据必须进入 Tool Result，不能在工具边界丢失。
5. 未知企业问题应先检索再拒答，不能通过硬编码问题清单伪造 Agent 行为。
6. 记录模型请求、真实执行结果和最终回答，才能验证模型选工具及定位错误。
