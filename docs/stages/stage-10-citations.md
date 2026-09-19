# 阶段 10：RAG Source Citation

## 目标和实际结构

HTTP 知识库回答附带可验证的文件名和 PDF 页码。保留原有 answer、session_id、path、tool_calls、llm_calls，只新增 sources。
下面省略原有调试字段：

```json
{
  "answer": "返回后十个工作日内提交。[demo-company-policy.pdf:p2:c1]",
  "sources": [{"document": "demo-company-policy.pdf", "page": 2}]
}
```

普通聊天、纯计算不补造文档来源，返回 `sources: []`。
本阶段沿用已有 parsing、chunking、retrieval、LangGraph、会话和工具逻辑，无新增依赖。

## 创建和修改的文件

| 文件 | 负责什么 |
| --- | --- |
| app/citations.py（新增） | resolve_citations：查找真实工具证据、核对引用、提取 metadata、按文件及页码去重 |
| app/agent.py（修改） | 最终回答生成后核对引用；State/返回值新增 sources；拒绝有检索但缺少有效引用的知识回答 |
| app/api.py（修改） | SourceResponse 定义 document/page；ChatResponse 新增 sources |
| tests/test_citations.py（新增） | 六项测试，覆盖去重、伪造、metadata、历史证据、HTTP 及实际 PDF 页码 |
| samples/verify_citations.py（新增） | 真实模型 + HTTP + 知识检索验收，重新解析 PDF 核对页面正文 |
| samples/citation_examples.json（生成） | 四轮真实输入、答案、来源、工具及路径记录，仅使用公开虚构测试 PDF |
| README.md（修改） | 阶段入口、运行和验收命令 |
| docs/stages/stage-10-citations.md（新增） | 本文 |

## 来源如何产生

```text
PDF 解析 enumerate(..., start=1)
  → metadata.source / page_number
  → chunk 保留 metadata，加 chunk_id
  → vector store 保留 metadata
  → search_knowledge_base 返回真实 chunks
  → tool message 保存真实结果
  → LLM 回答并选择 [chunk_id]
  → Python 与真实结果核对
  → 从对应 metadata 生成 document/page
  → 去重 → API sources
```

页码是 PDF 文件从 1 开始的物理页序号，不是 PDF 正文印刷的页码；封面也计入。
不从模型的文字、chunk_id 的 p2 字符或相似度推算页码。
索引来源本身必须正确：这一阶段复用经过验证的解析和 metadata 保存链路。

## 关键代码

`resolve_citations(answer, messages)` 先按 assistant Tool Call 的 ID 识别工具名，
仅接受对应 `search_knowledge_base` 的 tool message。
用户消息和 assistant 对来源的声明均不能成为证据。

```python
evidence[chunk_id] = {"document": document, "page": page}
```

此处 document 来自 `metadata["source"]`，page 来自 `metadata["page_number"]`。
要求名称和 chunk ID 为字符串、页码为正整数（排除 bool）。

模型只能选择证据，不能提供可信的来源字段。回答中的 PDF 方括号引用逐一核对：

```python
source = evidence.get(match.group(1))
if source is None:
    return ""
key = (source["document"], source["page"])
```

不存在的 PDF 引用标记被移除；存在的标记保留。
仅被有效引用的 chunks 进入 sources，不把所有 Top-K 结果都说成答案来源。
同一页的多个 chunks 或重复标记只产生一条 source；不同页保留，顺序按回答首次引用顺序。

`agent_node()` 在无工具请求的最终回答分支调用核对函数。
核对后的文本也写入 assistant 历史，避免把编造的 PDF 引用继续留在后续上下文。
若本轮检索返回了片段，但模型给出了没有有效来源的回答，而且未说明“没有足够依据”，
程序抛出 ValueError，API 返回原有 502 错误，并执行已有会话失败回滚。
程序不猜测应该给这段回答引用哪一页。

`SourceResponse` 使用 Pydantic：

```python
class SourceResponse(BaseModel):
    document: str
    page: int = Field(ge=1)
```

`ChatResponse.sources` 使用 `Field(default_factory=list)`。
旧请求无需更改，原有字段不删除；未提供 sources 的兼容调用返回空列表。

## 多轮对话兼容

读取完整 messages，包括 checkpoint 恢复的历史 Tool Result。
追问如果引用上一轮检索过的真实 chunk，即使本轮没有再次调用工具，也能返回正确 sources。
每一轮重新生成 sources，不直接复制上一轮的来源列表。
因此随后切换到问候或计算，不会仅因为会话曾检索过文档就自动带上旧来源。
工具执行和检索代码未复制；阶段 6 独立 run_rag 的旧编号及 metadata 输出保持原样，
本次结构化 Schema 升级面向当前 Agent 的 `/chat` 接口。

## 运行与验收

在项目目录运行单 worker 服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/docs`，POST /chat：

```json
{"message":"出差回来后多久提交报销？"}
```

检查响应 sources 为测试 PDF 第 2 页；带返回的 session_id 追问“那要提交哪些材料？”。
再在同一会话问候和计算，检查 sources 为空。

自动验证：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:HF_HUB_OFFLINE='1' # embedding 已缓存时使用
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe samples/verify_citations.py
```

真实脚本使用自己的 TestClient 进程，不依赖运行中的 uvicorn；需要有效 .env 配置和既有本地向量库。
不要同时运行其他访问相同 Qdrant 路径的命令。
脚本通过 `extract_pdf(samples / document)` 再解析原 PDF，
读取 `pages[page - 1]`，检查第 2 页确实包含“发票及费用说明”和“十个工作日”。

## 实际测试结果

2026-09-18，61 项测试全部通过，其中本阶段新增 6 项；包含既有三项真实 LLM calculator/聊天测试。
真实引用验收脚本也通过：

| 问题 | 本轮工具 | sources |
| --- | --- | --- |
| 出差回来后多久提交报销？ | search_knowledge_base | demo-company-policy.pdf，第 2 页 |
| 那要提交哪些材料？ | 无，使用历史证据 | 同上 |
| 你好，请介绍一下你自己。 | 无 | [] |
| 帮我计算 123 * 456 | calculator，结果 56088 | [] |

来源对应 PDF 的实际第 2 页，已重新解析确认。完整记录见 samples/citation_examples.json。
去重测试用同一页不同 chunk 验证；伪造测试保证 fake.pdf 不进入 answer 或 sources；
页码测试还故意让 chunk ID 的数字与 metadata 页码不一致，证明来源页码读取自 metadata。
没有出现实现失败。原有损坏 PDF 负面测试的 EOF 提示是预期测试输出。

## 边界与面试知识点

- “引用存在”与“内容被证据支持”是两个问题：本阶段保证输出来源来自实际检索证据，不证明每句话的语义都正确。
- LLM 可能选择相关性不足的真实 chunk；仍需检查检索质量和正文是否支持回答。
- 只支持当前 PDF 工具的 `[chunk_id]` 引用格式，不将模型任意自然语言提到的文件名当作来源。
- 正文没有有效引用的历史追问不会被自动猜测来源；系统提示仍要求知识回答标注 chunk。
- 以文件名和页码去重，与当前 metadata 设计一致；若未来不同目录存在同名文件，需要稳定 document_id。
- source 列表是被核对的回答引用，不是全部检索候选列表；tool_calls 仍保留完整检索结果和 metadata 供调试。
- 不新增存储敏感信息的机制；测试产物仅含虚构企业 PDF 和公开问题。

本阶段完成，停止后续开发。
