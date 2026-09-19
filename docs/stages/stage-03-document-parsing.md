# Stage 03：企业文档解析

## 范围和当前项目状态

本阶段完成本地 PDF → Python → 每页文本 → 页码及基础元数据。
不调用 LLM，不读取 API Key，不实现 OCR、Embedding、Vector DB、RAG 或 LangGraph。
检查时未找到 stage-02 文档；实际上一阶段材料为 README.md、EXECUTION_REPORT.md
及 tool_calling_test_results.txt。项目仍是终端 Tool Calling，FastAPI 只有讨论方案，未实现。
本阶段没有修改 app/main.py、app/tools.py 或已有 Tool Calling 测试。

## 技术选择

选择 pypdf：纯 Python、接口简单，只需 PdfReader 和 page.extract_text() 即可逐页读取文本。
这是文本型 PDF 的基础解析方案，不保证复杂排版、表格、多栏内容的阅读顺序。
扫描件中的图片不会自动转成文本；OCR 应作为后续单独选择，而不是在本阶段引入。
参考：[官方文本提取说明](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)。

生产依赖新增 pypdf；reportlab 单独放在 requirements-dev.txt，只生成虚构测试 PDF。
没有增加 Agent 或文档处理框架。

## 文件职责

| 文件 | 作用 |
|---|---|
| app/document_processing.py | extract_pdf()、错误处理及命令行 JSON 输出 |
| samples/create_sample.py | 用 reportlab 生成两页虚构中文企业制度 |
| samples/demo-company-policy.pdf | 无真实企业信息的可公开测试夹具 |
| samples/README.md | 样本说明及私有文件存放规则 |
| tests/test_document_processing.py | 实际 PDF 解析、空页、缺失、扩展名、损坏和加密测试 |
| requirements.txt | 增加生产解析依赖 |
| requirements-dev.txt | 样本生成依赖 |
| .gitignore | 忽略私有原文、解析输出和临时图片 |

## 数据流与关键代码

```text
命令行传入路径
→ extract_pdf(path)
→ 二进制打开本地文件
→ PdfReader(stream)
→ enumerate(reader.pages, start=1)
→ page.extract_text()
→ 文本及 metadata 列表
→ JSON 打印到终端
```

```python
with source.open("rb") as stream:
    reader = PdfReader(stream)
```

PDF 是二进制文件。with 在解析完成或失败后关闭文件，不保留文件句柄。
加密 PDF 当前明确拒绝，不尝试绕过密码。

```python
for page_number, page in enumerate(reader.pages, start=1):
    text = (page.extract_text() or "").strip()
```

enumerate 为每页附上从 1 开始的物理页码。extract_text() 可能返回 None，
因此用空字符串兜底。strip() 只去掉首尾空白，不重写正文或合并不同页面。

单页结果结构：

```json
{
  "text": "本页正文……",
  "metadata": {
    "source": "demo-company-policy.pdf",
    "page_number": 1,
    "page_count": 2,
    "title": "Fictional Company Policy",
    "text_status": "extracted"
  }
}
```

source 使用文件名，避免输出电脑绝对路径。title 来自 PDF 的 /Title，缺失时为空字符串。
无文本页仍保留记录、页码及 text_status="no_text"，不把后续页重新编号。
no_text 不能直接证明这是扫描件，也可能是真正空白页或字体映射导致提取失败。
页码是文件中第几页，不一定与正文印刷页码或 PDF 页标签相同。
同名文件可能冲突；当前样本范围内使用文件名，未来多文件系统应引入独立文档 ID。

## 运行及验证

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.document_processing samples/demo-company-policy.pdf
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_document_processing.py -v
```

重新生成样本需要开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe samples/create_sample.py
```

预期得到两个页面对象：第一页含工作及休假制度，第二页含差旅报销制度。
page_number 分别为 1、2，page_count 为 2，中文文本可读。

## 问题与处理

- stage-02 文档缺失：如实记录，不伪造上一阶段实施记录。
- 安装时旧 pip 按 GBK 读取 requirements-dev.txt 的 UTF-8 中文注释而失败：
  将注释改为 ASCII 后安装成功，无需修改系统设置。下载时 TLS 短暂失败经 pip 重试恢复。
- 样本使用中文 CID 字体，Poppler 提示替换为 SimSun；实际渲染检查两页中文可读，
  标题、正文和页脚没有遮挡。不同机器的字体显示仍可能不同。
- 文本为空：保留来源和页码，用 no_text 提示，当前不做 OCR。
- 加密文件：明确报错；损坏文件：将 PdfReadError 转为易理解的 ValueError。
- 扩展名只是初步检查，实际内容仍由 PdfReader 验证。
- 复杂文档：当前不宣称表格、版式或所有字体均能正确还原，需要用目标文档继续验收。
- 敏感信息：真实文件放 samples/private/，提取结果放 output/document-processing/；
  二者都被忽略。Git ignore 不会自动取消已跟踪文件，提交前需要检查暂存内容。
- 解析完全在本地执行，不发送原文到 LLM。

## 测试结果

2026-09-18 实际验证完成：

- Python 3.10.6，pypdf 6.19.0，reportlab 4.5.1。
- 真实两页中文 PDF 经命令行解析，第一页含“休假申请”，第二页含“差旅报销”。
- 页码为 1、2，总页数均为 2；标题 Fictional Company Policy，文本状态均为 extracted。
- 6 项解析测试全部通过：正文/元数据、空页、加密、损坏、缺失文件和扩展名。
- 原有 calculator 5 项、消息协议 3 项离线回归测试全部通过；未请求真实 LLM。
- pip check：No broken requirements found。
- Git 临时仓库实测：samples/private/ 和 output/document-processing/ 被忽略；
  公开的 demo-company-policy.pdf 未被忽略。当前项目尚未初始化 Git 仓库。
- 两页经 Poppler 渲染及目视检查，中文可读、版面完整。
- 损坏 PDF 测试中的 EOF marker not found 是故意构造错误输入的库警告，断言通过。

## 面试知识点

1. 文档解析与 RAG 的区别：解析产出文本和来源；RAG 还需要分块、检索及生成等环节。
2. 为什么逐页保留：未来文本分块仍应继承来源信息，便于引用及核对证据。
3. Schema 与元数据：Schema 描述结构；元数据记录这段文本来自哪里。
4. 文本型 PDF 与扫描 PDF：前者有文本对象，后者通常需要 OCR。
5. 为什么不能把空文本当解析成功：必须检查每页文本状态，并用真实样本断言内容。
6. 为什么不用 LLM 解析基础文本：本地库可完成本阶段任务，无需网络、密钥或模型费用。
7. 为什么拒绝加密文件：当前未实现授权密码输入及解密流程，避免隐藏失败。
8. 测试覆盖什么：正文正确、页码对应、元数据保留、错误明确；不宣称覆盖所有企业 PDF。
