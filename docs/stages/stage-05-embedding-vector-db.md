# Stage 05：Embedding + Vector Database

## 目标和范围

PDF → Text → Chunk → Embedding → 本地向量数据库。
query → Query Embedding → Cosine Search → Top-K chunks、分数及来源。
本阶段不让生成式 LLM 根据检索结果回答，不新增 FastAPI、RAG 或 Agent 框架。
复用阶段 3、4 的 extract_pdf()、ChunkConfig 和 chunk_pages()。

## 技术选择

- FastEmbed：通过 ONNX Runtime 在 CPU 上运行中文 embedding 模型。
- BAAI/bge-small-zh-v1.5：中文文本向量模型，512 维，首次下载约 90 MB。
- Qdrant Python 客户端的本地持久化模式：无需运行数据库服务或 Docker。
  使用 QdrantClient(path=...) 保存到项目 data/vector-db/。

相比生成式 API，这条链路不需要 API Key，不将 PDF 正文发送到外部模型服务。
首次安装和下载模型需要联网，模型缓存到 .cache/embeddings/。
之后模型在本机计算。不要把首次下载失败解释为已有 embedding 或测试成功。

官方资料：
[FastEmbed 支持模型](https://qdrant.github.io/fastembed/examples/Supported_Models/)、
[Qdrant 本地模式](https://github.com/qdrant/qdrant-client)、
[Qdrant 向量检索](https://qdrant.tech/documentation/search/)。

## 模块和职责

| 文件 | 职责 |
|---|---|
| app/embeddings.py | 模型配置、Embedder、文档和 query 的向量生成 |
| app/vector_store.py | 本地集合、保存正文/向量/metadata、相似度检索 |
| app/knowledge_base.py | 复用解析和切分，串联入库与查询，提供 CLI |
| tests/test_vector_store.py | 使用确定的小向量验证真实数据库，不下载模型 |
| samples/verify_vector_search.py | 使用真实中文模型和公开 PDF 做端到端验收 |
| samples/vector_search_example.json | 真实运行后保存的公开样本检索结果 |
| requirements.txt | 新增 fastembed、qdrant-client |
| .gitignore | 忽略向量库、模型缓存，沿用私有文档及输出规则 |

没有修改已有解析、切分及 Tool Calling 的核心逻辑。

## Embedding 是什么？

Embedding 模型把文本转换成一组浮点数，称为向量。
向量的各个数字不直接对应某个关键词；整体用于比较语义相关性。
本模型每条文本产生 512 个数字，这与 chunk 的字符长度是不同概念。
chunk 保存正文和 metadata，embedding 保存用于检索的数值表示。

```python
vectors = embedder.embed_documents([chunk["text"] for chunk in chunks])
```

Embedder.embed_documents() 调用模型的 passage_embed()；embed_query() 调用 query_embed()。
使用同一模型的文档和查询接口，保留该模型的 query/passage 预处理行为。
不能把不同模型生成的向量直接混合比较，即使维度相同。
数据库按模型名生成独立集合名，并在打开时检查向量维度及 Cosine 配置。
改变同名模型的实际权重或版本后应重新建库，当前没有实现权重版本管理。

## 入库数据流

```text
index 命令的 PDF 路径
→ extract_pdf()：逐页文本和 metadata
→ chunk_pages()：每页字符窗口
→ Embedder.embed_documents()：一块对应一个向量
→ VectorStore.save_chunks()
→ Qdrant 本地 collection
```

```python
models.PointStruct(
    id=identifier,
    vector=vector,
    payload={
        "text": chunk["text"],
        "metadata": metadata,
        "embedding_model": self.model_name,
    },
)
```

Qdrant point 包含 ID、向量和 payload。
全部 chunk metadata 原样存入 payload，包括 source、page_number、chunk_id、
page_count、title、text_status、chunk_number、start_char 和 end_char。
chunk_id 经 UUID5 转为 Qdrant 支持的 UUID；原 chunk_id 仍保留在 metadata 中。

重新索引时，先算好并校验新向量，再按文件名删除旧块并写入新块，避免重复及残留。
当前单文件名代表一个文档，同名 PDF 会相互替换；未来多文件来源需要独立文档 ID。
删除和写入不是原子事务，中途失败应重新运行入库。当前未实现增量更新或并发写入。
空文本 PDF 明确报错，不写入数据库，也不会删除已有记录。

## 查询和 Top-K

```text
用户 query
→ Embedder.embed_query()
→ 512 维 query vector
→ VectorStore.search(vector, top_k)
→ 按 cosine score 排序的 chunks
→ 输出正文、分数和来源
```

```python
hits = self.client.query_points(
    collection_name=self.collection,
    query=query_vector,
    limit=top_k,
    with_payload=True,
).points
```

Top-K 是最多返回多少块，默认 DEFAULT_TOP_K=3，可用 --top-k 配置，必须是正整数。
库里只有 3 块时，Top-K=10 也最多返回 3 块；空库返回空列表。
它不是分数阈值，即使文档不相关，仍可能返回最近的几个结果。

Cosine similarity 比较向量方向，分数越高越相似，分数不是答案正确率或概率。
本地 Qdrant 使用精确扫描，适合当前小型作品集，不声明具备大型近似索引性能。
本阶段不添加 ANN 索引、混合检索、重排序或生成回答。

## 运行

在项目根目录安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

首次运行会下载模型。建立公开样本库，使用阶段 4 已验收的 80/20 切分：

```powershell
.\.venv\Scripts\python.exe -m app.knowledge_base index samples/demo-company-policy.pdf --chunk-size 80 --overlap 20
```

检索：

```powershell
.\.venv\Scripts\python.exe -m app.knowledge_base search '出差回来后，多久之内要提交报销？' --top-k 2
```

不传 size/overlap 时复用 ChunkConfig 的 500/50 默认值；入库使用不同参数会改变块数量。
数据库路径和模型也可配置，参数放在子命令之前：

```powershell
.\.venv\Scripts\python.exe -m app.knowledge_base --db-path data/vector-db/demo search '休假如何申请？' --top-k 1
```

同一 Qdrant 本地目录只能由一个客户端进程打开；不要同时运行多个命令占用同一路径。
CLI 和测试会在 finally 中关闭客户端。

## 验收

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_vector_store.py -v
.\.venv\Scripts\python.exe samples/verify_vector_search.py
```

第一条使用确定的小向量测试真实数据库协议，不证明中文语义模型有效。
第二条才使用真实 embedding：公开 PDF 入库后关闭数据库，再重新打开进行 Top-K=2 检索。
预期第一名是第 2 页 demo-company-policy.pdf:p2:c1，包含“十个工作日”。
只有实际模型运行且断言通过后，才能将端到端验收记录为成功。

2026-09-18 实际运行结果：

- Python 3.10.6；fastembed 0.7.4；qdrant-client 1.19.1；onnxruntime 1.23.2。
- PDF 2 页 → 80/20 切分产生 3 chunks → 每块生成 512 维真实中文向量 → 保存成功。
- 关闭本地数据库后重新打开，query 产生 512 维向量，Top-K=2 返回 2 块。

| 排名 | cosine score | 来源 | 页码 | chunk_id |
|---|---|---|---|---|
| 1 | 0.7140739043354478 | demo-company-policy.pdf | 2 | demo-company-policy.pdf:p2:c1 |
| 2 | 0.5756943795704452 | demo-company-policy.pdf | 1 | demo-company-policy.pdf:p1:c2 |

第一名正文包含“报销期限：返回后十个工作日内提交。”，真实语义检索断言通过。
第二名为休假申请文字，相关性更低，说明 Top-K 不保证每个结果都适合回答问题。
完整正文及全部元数据见 samples/vector_search_example.json。

- 5 项真实数据库测试全部通过：持久化/排序/metadata、重新入库、非法参数、模型隔离和维度不匹配。
- 21 项原有离线回归测试全部通过：calculator 5 项、消息协议 3 项、解析 6 项、切分 7 项。
- 使用 HF_HUB_OFFLINE=1 再运行 CLI 的 Top-K=1 搜索，通过，确认缓存模型可离线使用。
- CLI Top-K=0 明确报错且非零退出，通过。
- pip check 通过，缓存及向量数据库的 Git 忽略规则验证通过。
- 本阶段没有调用生成式 LLM，没有生成最终自然语言答案。

## 局限和问题

- 首次安装申请遇到自动审批超时，命令未运行；按系统允许方式重试后安装成功。
- Windows 模型缓存不支持符号链接时退化为普通文件缓存，会多占磁盘，不影响本次模型运行。
- 公开模型无 HF_TOKEN 也完成了下载，本次不需要额外配置密钥。

- 模型有输入 token 上限，字符数不能精确代表 token 数；过长内容可能被模型截断。
  当前验收块为 80 字符短文本。后续大文档应检查 token 长度与分块配置，不能假设全部内容被编码。
- 检索质量依赖模型、切分和问题，单个样本成功不保证所有企业问题都能命中。
- 仅做本地检索，不生成最终答案；JSON 中正文是原始 chunk，不是 LLM 回答。
- 向量库里包含正文和 metadata，也属于敏感数据，应保持 Git 忽略。
- 真实文件放 samples/private/，其检索输出放 output/document-processing/，不要提交到公开示例。

## 面试知识点

1. Embedding 是语义表示，向量数据库存储表示并执行相似度查询。
2. 文档和 query 要进入一致的向量空间，模型变化后通常需要重新索引。
3. Top-K 控制结果数量，不自动证明相关，也不等于可信度阈值。
4. metadata 不参与默认 cosine 计算，但对来源引用、过滤和排查十分关键。
5. 检索与生成分离：本阶段找到证据，下一步是否生成答案需另行设计。
6. 持久化必须关闭后重开验证，不能只在同一个内存对象里查到结果就宣称成功。
