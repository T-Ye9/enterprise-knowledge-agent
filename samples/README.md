# PDF 测试样本

`demo-company-policy.pdf` 是自行生成的两页虚构企业制度，不包含真实企业信息。
内容包括工作时间、休假申请和差旅报销，供解析和页码验证使用。

重新生成（需安装 requirements-dev.txt）：

```powershell
.\.venv\Scripts\python.exe samples/create_sample.py
```

真实企业文件只能放在 `samples/private/`，该目录已被 .gitignore 忽略。
真实文件的文本或 JSON 输出只保存在被忽略的 `output/document-processing/`。
不要把真实文件、解析结果或截图复制到测试夹具、阶段文档或日志中。
忽略规则不会移除已经被 Git 跟踪的文件；提交前仍须检查 git status 和暂存内容。
