# Stage 04：Document Chunking

## 目标与范围

复用阶段 3 的 extract_pdf()，完成 Document → Pages → Text → Chunks。
本阶段只生成文本块及来源元数据，不实现 Embedding、Vector DB 或 RAG，不请求 LLM。
没有修改 PDF 解析模块、Tool Calling 逻辑或依赖清单。

## 文件

| 文件 | 职责 |
|---|---|
| app/chunking.py | ChunkConfig、chunk_pages()、PDF 切分命令行入口 |
| tests/test_chunking.py | 重叠、覆盖、边界、来源信息及真实 PDF 集成测试 |
| samples/chunk_examples.json | 已运行生成的公开虚构 PDF 的 3 个实际 chunk |
| README.md | 本阶段运行入口 |

## 简单的切分策略

每页独立按字符数切分，默认 chunk_size=500、overlap=50。
不合并页面，不跨页重叠，因此每块只对应一个物理页码。
空白页不生成 chunk，但后续页面继续保留原页码，不重新编号。
不对块内文本 strip()，以便字符位置始终对应阶段 3 的原始页面文本。
只包含空白的窗口不输出。

选择字符滑动窗口是为了实现可读、行为确定、便于测试，没有引入切分框架或 tokenizer。
它会切开句子、标题或表格，不能保证每块语义完整。按页切分也会割开跨页的段落。
这是当前阶段的基础方案，默认数值是学习起点，不是经过检索效果评估的最优值。

## 集中配置

```python
@dataclass(frozen=True)
class ChunkConfig:
    chunk_size: int = 500
    overlap: int = 50
```

frozen=True 防止意外改动配置；默认值只在这里定义。
DEFAULT_CONFIG = ChunkConfig() 被函数默认参数和命令行默认值复用。
调用方可以传 ChunkConfig(80, 20)，或通过 --chunk-size、--overlap 覆盖。
校验要求两个值均为整数，chunk_size > 0，0 <= overlap < chunk_size。
否则可能出现无意义切分或无法前进的窗口。

## 数据流和关键代码

```text
PDF 路径
→ extract_pdf(path)
→ [{text, metadata}, ...] 按页结果
→ chunk_pages(pages, config)
→ [{text, metadata}, ...] 按块结果
→ JSON 输出
```

```python
step = config.chunk_size - config.overlap
for start in range(0, len(text), step):
    end = min(start + config.chunk_size, len(text))
    chunk_text = text[start:end]
```

例如 size=80、overlap=20，每次起点前进 60 字符。
第一个窗口 [0, 80)，第二个窗口从 60 开始；字符 60 至 79 重复出现。
当 end 达到页面长度立即停止，不额外输出完全包含于上一块的重叠尾片。

```python
"metadata": {
    **metadata,
    "chunk_id": f"{source}:p{page_number}:c{chunk_number}",
    "chunk_number": chunk_number,
    "start_char": start,
    "end_char": end,
}
```

**metadata 复制阶段 3 的来源、页码、总页数、标题和文本状态。
chunk_number 每页从 1 开始；chunk_id 由文件名、页码、页内序号组成。
字符范围采用 Python 切片规则：起点包含，终点不包含，基于提取后的页面文本。
它不是 PDF 的字节位置，也不是模型 token 位置。
原页面字典不被修改；同样输入和配置产生相同结果。

当前 ID 只适用于文件名不重复的单次输入。同名文件、文档更新或改变切分配置后，
ID 可能冲突或指向不同文本，不应当作跨版本的全局永久 ID。
未来多文档/多版本系统需要文档 ID 或内容版本信息，本阶段不引入该机制。

## 为什么不把整个 PDF 一次发送给 LLM？

小型 PDF 的文本可能可以一次发送，并非技术上绝对不允许。
但对于长文档或多份企业文档，这通常不合适：

- 模型有上下文长度上限，还要留空间给问题、提示和输出。
- 每次发送大量无关内容会增加处理成本和延迟。
- 相关信息可能被大量无关内容淹没。
- 按块保留来源便于后续定位证据和引用页码。

切分让后续系统能够按问题选取相关部分；本阶段尚未实现检索或回答。

## chunk size 是什么？

它是一块文本的目标长度上限。本项目用 Python 字符数计算，len(text) 包括标点、空格和换行。
最后一块可能更短；短页面可能只产生一块。
不同语言和模型的 token 编码不同，因此 500 字符不等于 500 token。
未来对接模型需要另外确认实际 token 预算，本阶段不新增 tokenizer。

## overlap 为什么存在？

一句话或一条规则可能刚好被边界切开。让相邻块重复部分文字，可以保留一些上下文，
减少边界信息断裂的影响。它不能保证完整语义，尤其不能修复跨页上下文。
重复文本也会增加块数和后续索引/请求开销，所以 overlap 不是越大越好。

## 太大或太小有什么问题？

| 设置 | 好处 | 问题 |
|---|---|---|
| 较大 chunk | 上下文较完整、块数较少 | 可能混入多个主题，后续检索更粗，输入成本较高 |
| 较小 chunk | 定位较细、单块输入较短 | 可能缺少主语、前提和规则上下文，块数更多 |
| 较大 overlap | 边界附近保留更多文字 | 冗余增加，后续可能取到多个重复证据 |
| overlap=0 | 无重复、开销较低 | 边界处更容易丢失完整语境 |

应根据文档、问题和后续检索质量调整，不仅凭字符长度判断好坏。

## 运行

在项目根目录执行，无需新增依赖或配置 API Key：

```powershell
.\.venv\Scripts\python.exe -m app.chunking samples/demo-company-policy.pdf
```

默认 500/50 下，该短样本每页都能放进一块，共 2 块。
为了演示切分与重叠，实际验收使用较小窗口：

```powershell
.\.venv\Scripts\python.exe -m app.chunking samples/demo-company-policy.pdf --chunk-size 80 --overlap 20
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_chunking.py -v
```

## 3 个实际 chunk 示例

来自公开虚构样本，不含真实企业信息。完整原样结果见 samples/chunk_examples.json。

### demo-company-policy.pdf:p1:c1

source=demo-company-policy.pdf，page_number=1，字符范围 [0, 80)。

```text
虚构企业制度：工作与休假
此文件仅用于测试，不包含真实企业信息。
工作时间：周一至周五，上午九点至下午六点。
休假申请：请提前三个工作日向主管提交申请。
第 1
```

### demo-company-policy.pdf:p1:c2

source=demo-company-policy.pdf，page_number=1，字符范围 [60, 90)。
与上一块重复 20 字符，可看到休假规则部分出现在两个块里。

```text
请提前三个工作日向主管提交申请。
第 1 页 / 共 2 页
```

### demo-company-policy.pdf:p2:c1

source=demo-company-policy.pdf，page_number=2，字符范围 [0, 76)。
页面短于 80 字符，只有一块。

```text
虚构企业制度：差旅报销
差旅需要事先获得主管批准。
报销规则：员工需提交发票及费用说明。
报销期限：返回后十个工作日内提交。
第 2 页 / 共 2 页
```

## 测试结果和问题

2026-09-18：7 项 chunking 测试和 6 项 PDF 解析回归测试全部通过。
chunking 验证了重叠和全文覆盖、不跨页、元数据复制、空页不改页码、
精确边界无冗余尾片、零重叠、非法配置，以及真实 PDF 切分和 ID 可重复生成。
没有调用外部 API。

没有发现需要修复的运行错误。PDF 损坏文件测试中的 EOF marker not found 是预期库警告。
示例中第一块在页脚中间结束，是字符切分的真实局限，不将其伪装成语义切分。
当前保留页眉页脚，不做清洗；元数据页码独立于正文中的印刷页码。
私有文件输出继续只能保存在被忽略的 output/document-processing/，不要提交敏感 chunks。

## 面试知识点

- 解析产出页面，切分产出可独立处理的文本块，两者保持模块分离。
- 来源元数据必须随块传播，未来引用才能回到原文。
- 字符数与 token 数不同；chunk size 需要结合实际任务评估。
- overlap 是上下文保留与冗余开销之间的取舍。
- 有 chunks 不代表已经实现 RAG，还没有 Embedding、索引、检索或生成链路。
