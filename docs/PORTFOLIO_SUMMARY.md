# Portfolio Summary

本页用于简历与面试表达。所有数字来自 [Stage 17 最终 QA](stages/stage-17-final-qa.md)；尚无已验收的公开 Live Demo。

## 项目一句话介绍

基于 RAG 与 LangGraph 的企业 PDF 知识助手，支持工具调用、多轮问答和可核对来源。

## 简历版项目描述

- 使用 pypdf、FastEmbed 本地 ONNX 模型和 Qdrant 构建 PDF 解析、切块与检索链路；在 19 条公开开发集上，直接 Top-3 检索的全部证据覆盖为 10/11。
- 基于 LangGraph 编排 DeepSeek 原生 Tool Calling，实现计算、企业知识检索和直接回答；真实评测工具选择 19/19，且用检索 metadata 核对文档引用。
- 使用 FastAPI、React/TypeScript 和 SSE 实现可追问的 Web 聊天；完成 109 项后端测试、前端构建与浏览器测试，并验证 Docker 冷启动自动重建 Demo 知识库。

## English Resume Version

- Built a PDF-to-retrieval pipeline with pypdf, local ONNX embeddings, and Qdrant; direct Top-3 retrieval covered all expected evidence in 10 of 11 applicable cases on a small public development set.
- Orchestrated DeepSeek function calling with LangGraph for calculator, knowledge search, and direct replies; observed correct tool selection in 19 of 19 evaluation cases and validated citations against retrieved metadata.
- Delivered a FastAPI and React/TypeScript chat UI with SSE and short-term sessions; passed 109 backend tests and verified frontend builds, browser flows, and Docker cold-start knowledge-base recovery.

## 30 秒项目介绍

我做了一个企业 PDF 知识助手，用户能问制度问题、继续追问，也能让 Agent 做计算。技术上，先把 PDF 解析、切块、向量化并存入本地 Qdrant，再让 LangGraph 根据 DeepSeek 的工具调用结果选择直接回答、计算或知识检索。文档答案附带真实检索片段的文件名和页码。我还做了 19 条小型评测，明确记录了一条多事实检索漏失，而不是只展示成功案例。

## 2 分钟项目介绍

这个项目解决的是“企业文档能搜到，但回答需要有依据”的问题。用户通过 React 页面发消息，FastAPI 调用 LangGraph Agent。Agent 使用 DeepSeek 的原生 Tool Calling：问候可直接回答，数学题调用真实 Python calculator，企业制度题调用知识搜索工具。工具结果带调用 ID 返回模型，所以模型能在看到真实结果后生成最终回答。

知识库由两份公开虚构 PDF 演示。pypdf 按页解析；切块时保留文件名、页码和 chunk ID；FastEmbed 在本地 CPU 上生成中文向量，Qdrant 本地模式执行相似度检索。知识工具只返回检索证据，不复制一套 RAG。独立 RAG 模块也可直接测试。模型选择引用标记后，Python 根据真实工具结果解析并去重来源，避免凭空编造文档页码。

工程上我用了进程内短期会话、SSE 流式输出、FastAPI 请求校验与错误处理。公开 Demo 模式可从内置 PDF 在容器启动时重建知识库。本地最终 QA 有 109 项后端测试通过，19 条真实模型评测的工具选择为 19/19；但单次 Top-3 直接检索对一条跨三处事实的问题只覆盖其中部分证据，所以我把它记录为限制。当前还没有经过验收的公网 Demo，也没有把这些小样本数字当成生产效果。

## 5 个项目亮点

1. 从手写原生工具协议逐步升级到 LangGraph，能解释模型决策、参数、Python 执行、工具回传的完整闭环。
2. 知识工具复用既有向量检索，Agent 和独立 RAG 模块职责清晰。
3. 来源字段从检索 metadata 得到，而非相信模型自由编写的文件名和页码。
4. 无持久卷公开 Demo 可用两份虚构 PDF 自动重建知识库，并经过 Docker 冷启动验收。
5. 评测同时呈现通过项和 `M02` 失败项，能讨论 Top-K、证据覆盖与规则评分的边界。

## 5 个面试追问

1. 模型返回的 `tool_calls` 如何变成真实 Python 函数调用？参数错误时如何处理？
2. LangGraph 的 State、两个 Node 和条件 Edge 怎样防止无限工具循环？
3. 为什么引用标记不能直接信任 LLM？`sources` 的文件名和页码如何核对？
4. `M02` 为什么出现“来源页看似命中但证据仍缺失”？提高 Top-K 是否一定有用？
5. 如果会话、文档和并发规模增长，当前 Qdrant 本地模式、`InMemorySaver` 和全局限流需要怎样演进？

> 面试展示时可从 [README](../README.md) 演示本地流程。没有公开网址时请说“本地 Demo / 已完成部署准备”，不要说“已上线”。
