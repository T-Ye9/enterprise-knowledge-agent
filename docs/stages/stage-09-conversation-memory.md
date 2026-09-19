# 阶段 9：短期多轮对话

## 目标与范围

同一会话中的追问能引用前几轮问题、回答和真实 Tool Result。
复用已有 agent/tools 节点、calculator、知识库检索；不修改 ingestion、RAG 或工具选择逻辑。
不增加 Redis、长期记忆、数据库或新依赖。终端 main.py 保持单轮；本阶段会话入口是 HTTP。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| app/conversation_memory.py | UUID 会话登记；持有一个共享 InMemorySaver；删除全部 checkpoint |
| app/agent.py | 编译时连接 checkpointer；恢复历史；追加用户消息；失败回滚 |
| app/api.py | 校验 session_id；新建/删除接口；将会话信息传给 Agent |
| tests/test_conversation_memory.py | 三轮消息协议、隔离、计数重置、失败回滚和 API 生命周期 |
| tests/test_api.py | 更新委托断言，验证 HTTP 将会话参数传给 Agent |
| samples/verify_conversation.py | HTTP TestClient + 真实模型/工具的三轮验收 |
| samples/conversation_examples.json | 此次真实验收的输入、回答、路径、工具参数、来源和 ID |
| README.md | 启动与验收入口 |

## 为什么选择 InMemorySaver

现有 LangGraph 已安装 langgraph-checkpoint，直接使用 `langgraph.checkpoint.memory.InMemorySaver`。
它保存图的 State 快照。`thread_id` 是 LangGraph 区分会话的键，HTTP 层叫 `session_id`，两者使用同一个 UUID 字符串。
无须自行维护第二份聊天历史，也不用引入 Redis。适合本地作品集和短期交互。

## 关键代码与数据流

`ConversationMemory.create()` 用 `str(uuid4())` 生成 ID，登记在 `session_ids`；API 校验已登记 ID。
`build_agent(..., checkpointer=...)` 最后执行：

```python
return builder.compile(checkpointer=checkpointer)
```

`run_agent()` 构造配置并恢复上一轮 State：

```python
config["configurable"] = {"thread_id": session_id}
previous = graph.get_state(config).values
messages = list(previous.get("messages", [{"role": "system", "content": SYSTEM_PROMPT}]))
messages.append({"role": "user", "content": user_input})
```

首次没有历史，加入一条 system 消息；后续恢复历史，不重复 system。
State 的 messages 使用完整列表替换，没有 add_messages reducer；这是延续现有字典消息设计，避免重复追加。
历史含 assistant.tool_calls、对应 tool_call_id 的工具结果、最终回答，保留原生 Tool Calling 协议。
llm_calls、tool_calls、path、final_answer 每次 invoke 重置，因此 4 次 LLM 上限是每个用户轮次的预算。

```text
POST /chat {message, session_id}
  → 校验 UUID 和会话是否存在
  → session_id 映射到 thread_id
  → checkpoint 恢复 messages + 新用户问题
  → agent → [tools → agent，必要时重复] → END
  → checkpoint 保存完整 State
  → 返回 session_id、answer、本轮 path/tool_calls/llm_calls
下一轮带同一 session_id 重复以上流程
```

工具选择仍是 `tool_choice="auto"`。程序没有通过“那”“提前”等关键词选择工具。
LLM 可以重新检索，也可以使用之前 Tool Result 中已经出现的证据。后续轮 tool_calls 为空并不表示它没有上下文。

## 失败处理

模型或图执行失败时可能留下未完成的 assistant Tool Call，不能直接当作下一轮历史发送。
`run_agent()` 在异常时先 `checkpointer.delete_thread(session_id)`，
若有上一轮完整 State，再 `graph.update_state(config, previous, as_node="agent")` 恢复它，随后重新抛出异常。
上一轮最终 assistant 无待执行 Tool Call，条件边路由到 END。
没有历史的首次失败只删除中间快照。API 继续使用原来的 502/504/508 错误处理，并关闭客户端。
失败回滚测试验证旧成功轮保留、失败问题和中间 Tool Call 均未进入下一次模型请求。

## 会话接口

- `POST /sessions`：201，返回 `{"session_id":"UUID"}`，不访问 LLM。
- `POST /chat` 不传 ID：自动新建，200 响应带 ID。
- `POST /chat` 带 ID：继续已有会话。无效 UUID 返回 422；未登记/已删除 ID 返回 404。
- `DELETE /sessions/{session_id}`：204，删除全部 checkpoints 和登记 ID。重复删除返回 404。
- 清空后开始新对话：删除旧会话，再新建或发送不带 ID 的 /chat。
- `GET /health`：仍返回 `{"status":"ok"}`。

## 如何运行和验证

项目目录中运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

访问 `/docs` 操作接口。PowerShell 连续对话示例：

```powershell
$base = 'http://127.0.0.1:8000'
$session = Invoke-RestMethod -Method Post -Uri "$base/sessions"
foreach ($question in @('出差回来后，多久之内要提交报销？', '那要提交哪些材料？', '需要提前批准吗？')) {
    $body = @{message=$question; session_id=$session.session_id} | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "$base/chat" -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
}
Invoke-RestMethod -Method Delete -Uri "$base/sessions/$($session.session_id)"
```

自动验收（自己的 TestClient 进程，无需启动 uvicorn）：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:HF_HUB_OFFLINE='1' # 本机已缓存 embedding 模型时使用
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe samples/verify_conversation.py
```

真实测试需要本地 .env 的有效 DeepSeek 配置和阶段 5 已入库的虚构 PDF。
不要同时运行访问同一路径 Qdrant 的其他命令。

## 实际结果

2026-09-18：55 项测试通过，包含原有 3 项真实 LLM 工具测试；新增 4 项会话测试。
真实连续三轮全部使用同一 ID：

| 轮次 | 输入 | 实际路径 | 回答要点 |
| --- | --- | --- | --- |
| 1 | 出差回来后，多久之内要提交报销？ | START → agent → tools → agent → END | 返回后十个工作日内提交 |
| 2 | 那要提交哪些材料？ | START → agent → END | 发票及费用说明 |
| 3 | 需要提前批准吗？ | START → agent → END | 差旅需要事先获得主管批准 |

第一轮工具名 `search_knowledge_base`，参数 `{"query":"出差回来后报销提交时限"}`。
第二、三轮没有再次调用工具，引用第一轮已获得的 `demo-company-policy.pdf:p2:c1`。
删除返回 204；继续使用旧 ID 返回 404。完整来源 metadata 保留在验收 JSON 中。
没有遇到实现测试失败。损坏 PDF 的既有负面测试会打印 `EOF marker not found`，该测试仍通过。

## 内存与安全边界

checkpointer State 只含消息、工具记录、路径、计数和回答；不包含 OpenAI 客户端、API Key 或 .env 配置。
用户消息和工具正文仍属于会话内容，不应主动提交密钥或敏感资料；示例记录只使用虚构 PDF。
验收 JSON 是脚本显式生成的测试产物，不是自动持久化所有会话的日志。
会话和 checkpoints 仅在一个 Python 进程中存在，重启/热重载即消失；多个 worker 不共享会话。
本阶段没有 TTL、历史截断或身份认证。删除会话可释放对应快照；历史和中间快照会随使用增长，长会话会增加上下文长度及调用成本。
session_id 用于区分上下文，不是用户身份认证凭证。当前保留串行 CHAT_LOCK，兼容 Qdrant 本地模式。
这是短期对话上下文，不是跨会话的长期个人记忆。

## 面试知识点

1. State 是图处理的数据；checkpoint 是 State 的快照；thread_id 把快照关联到会话。
2. 多轮不是重新训练模型，而是把历史消息与当前问题一起发送给模型。
3. 工具证据与 Tool Call 必须配对保留；只保留最终自然语言回答可能丢失来源。
4. 上下文可能影响工具选择，但决定仍来自模型的 Tool Calling 响应。
5. 每轮循环预算应重置，不能因连续对话而累计到上限。
6. checkpoint 不等于事务成功；失败轮的中间状态需要回滚。
7. 短期会话和知识库不同：前者记录交互，后者提供可检索的企业事实。

参考：[LangGraph 官方 memory 示例](https://github.com/langchain-ai/docs/blob/main/docs/src/oss/langgraph/add-memory.mdx)、
[InMemorySaver.delete_thread 官方参考](https://reference.langchain.com/python/langgraph.checkpoint/memory/InMemorySaver/delete_thread)。
