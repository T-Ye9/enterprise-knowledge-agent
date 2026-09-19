"""python -m evaluation.run --mode retrieval|agent|replay。"""
import argparse
import contextlib
import hashlib
import importlib.metadata
import io
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from .metrics import SCORER_VERSION, normalize, score_case, summarize

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluation" / "dataset.json"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset():
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    from app.document_processing import extract_pdf
    pages = {name: extract_pdf(ROOT / "samples" / name) for name in dataset["corpus"]}
    ids = [case["id"] for case in dataset["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("dataset case id 必须唯一")
    for case in dataset["cases"]:
        for fact in case.get("facts", []):
            page = pages[fact["document"]][fact["page"] - 1]
            if normalize(fact["quote"]) not in normalize(page["text"]):
                raise ValueError(f"{case['id']} 的预期证据不在原 PDF 指定页中")
    fingerprint = {"dataset_sha256": sha256(DATASET),
                   "corpus_sha256": {name: sha256(ROOT / "samples" / name) for name in dataset["corpus"]}}
    return dataset, fingerprint


def write_report(report, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# RAG / Agent Evaluation Report", "", f"Mode: **{report['mode']}** · {report['created_at']}", "",
             "仅对公开虚构样例评分；确定性规则不是完整语义真实性证明。", "",
             f"Scorer version: {report.get('scorer_version', 1)}", "",
             f"Dataset: {len(report['cases'])} cases · Top-K: {report['config']['top_k']} · "
             f"Chunk: {report['config']['chunk_size']}/{report['config']['overlap']}", "",
             f"Embedding: {report['embedding_model']} · LLM: {report.get('llm_model') or '未调用'}", "",
             "## 指标（只统计适用的案例）", "", "| Metric | Passed / Total | Rate |", "| --- | --- | --- |"]
    for name, metric in report["summary"]["metrics"].items():
        lines.append(f"| {name} | {metric['passed']} / {metric['total']} | {metric['rate']:.1%} |")
    lines += ["", "未列出的指标为 N/A，不表示 100%。agent_completed 只表示有有效回答，其他指标分别评估质量。", "", "## Latency", ""]
    if report["mode"] == "replay":
        lines.append("以下耗时来自原始运行记录，不是本次重新评分的耗时。")
    for kind, latency in report["summary"]["latency"].items():
        lines.append(f"- {kind}: n={latency['count']}, p50={latency['p50_seconds']:.3f}s, p95={latency['p95_seconds']:.3f}s")
    lines += ["", "初始化/入库时间不计入单条延迟；Agent 不含 HTTP/React 时间。p95 使用 nearest-rank。", "",
              "## 逐条检查", "", "| ID | Category | Result | Failed checks |", "| --- | --- | --- | --- |"]
    for row in report["cases"]:
        failed = [name for name, passed in row["checks"].items() if not passed]
        result = "FAIL" if failed else "PASS" if row["checks"] else "N/A"
        lines.append(f"| {row['id']} | {row['category']} | {result} | {', '.join(failed) or '—'} |")
    lines += ["", "## 边界", "", "这是开发集，不是隐藏测试集；样本少、PDF 短，来源命中不能替代事实依据检查。",
              "答案规则只覆盖预声明事实；未声明的编造句、否定、关系错误可能漏检。同义改写可能误判失败。",
              "拒答规则检查固定拒答语及数量是否出现在实际引用证据中，不证明模型完全没有补造规则或关系。",
              "真实 LLM 运行有随机性；replay 只重放评分，不重新检索或调用模型。",
              "完整问题、检索块、答案、工具参数、来源、环境版本与 SHA256 在同名 JSON 中。", ""]
    output.with_suffix(".md").write_text('\n'.join(lines), encoding="utf-8")


def run(mode, dataset, fingerprint, top_k):
    from app.agent import run_agent
    from app.chunking import ChunkConfig
    from app.embeddings import Embedder
    from app.knowledge_base import index_pdf, search_query
    from app.llm_client import create_client
    from app.vector_store import VectorStore
    client = None
    model = None
    if mode == "agent":
        client, model = create_client()
    rows = []
    setup_started = time.perf_counter()
    try:
        embedder = Embedder()
        config = ChunkConfig(dataset["config"]["chunk_size"], dataset["config"]["overlap"])
        with TemporaryDirectory(prefix="knowledge-evaluation-") as directory:
            database = Path(directory) / "vectors"
            store = VectorStore(database, embedder.dimension, embedder.model_name)
            try:
                ingestion = [index_pdf(ROOT / "samples" / name, embedder, store, config) for name in dataset["corpus"]]
            finally:
                store.close()
            setup_seconds = time.perf_counter() - setup_started
            # 只在独立评测进程中替换数据库路径，调用真实知识工具，不复制工具检索逻辑。
            with patch("app.knowledge_base.DATABASE_PATH", database):
                for case in dataset["cases"]:
                    row = {"id": case["id"], "category": case["category"], "question": case["question"]}
                    if "search_knowledge_base" in case["expected_tools"]:
                        started = time.perf_counter()
                        store = VectorStore(database, embedder.dimension, embedder.model_name)
                        try:
                            try:
                                row["retrieval"] = search_query(case["question"], embedder, store, top_k)
                            except Exception as error:
                                row["retrieval_error"] = type(error).__name__
                        finally:
                            store.close()
                        row["retrieval_seconds"] = time.perf_counter() - started
                    if mode == "agent":
                        started = time.perf_counter()
                        try:
                            with contextlib.redirect_stdout(io.StringIO()):
                                row["trace"] = run_agent(client, model, case["question"])
                        except Exception as error:
                            row["agent_error"] = type(error).__name__
                        row["agent_seconds"] = time.perf_counter() - started
                    row["checks"] = score_case(case, row, mode == "agent")
                    rows.append(row)
                    failed = [name for name, passed in row["checks"].items() if not passed]
                    print(f"{case['id']}: {'FAIL ' + ', '.join(failed) if failed else 'PASS' if row['checks'] else 'N/A'}", flush=True)
    finally:
        if client is not None:
            client.close()
    return {"mode": mode, "scorer_version": SCORER_VERSION, "created_at": datetime.now(timezone.utc).isoformat(), **fingerprint,
            "config": {**dataset["config"], "top_k": top_k}, "embedding_model": embedder.model_name,
            "llm_model": model, "setup_seconds": setup_seconds, "ingestion": ingestion,
            "environment": {"python": platform.python_version(), **{name: importlib.metadata.version(name)
                            for name in ["openai", "langgraph", "fastembed", "qdrant-client", "pypdf"]}},
            "cases": rows, "summary": summarize(rows)}


def replay(path, dataset, fingerprint):
    original = json.loads(path.read_text(encoding="utf-8"))
    for key, value in fingerprint.items():
        if original[key] != value:
            raise ValueError("dataset 或 PDF 已变更，不能将旧记录作为同一基线重新评分")
    cases = {case["id"]: case for case in dataset["cases"]}
    if len(original["cases"]) != len(cases) or {row["id"] for row in original["cases"]} != set(cases):
        raise ValueError("记录缺少或重复案例")
    agent_mode = original.get("recorded_mode", original["mode"]) == "agent"
    for row in original["cases"]:
        row["checks"] = score_case(cases[row["id"]], row, agent_mode)
    return {**original, "mode": "replay", "recorded_mode": "agent" if agent_mode else "retrieval",
            "scorer_version": SCORER_VERSION, "recorded_scorer_version": original.get("scorer_version", 1),
            "original_created_at": original.get("original_created_at", original["created_at"]), "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": summarize(original["cases"])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["retrieval", "agent", "replay"], default="retrieval")
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, help="不含扩展名的报告路径")
    args = parser.parse_args()
    dataset, fingerprint = load_dataset()
    top_k = args.top_k if args.top_k is not None else dataset["config"]["top_k"]
    if top_k <= 0:
        parser.error("top-k 必须大于 0")
    if args.mode == "replay":
        if args.input is None or args.top_k is not None:
            parser.error("replay 需要 --input，且不能修改原记录的 top-k")
        report = replay(args.input, dataset, fingerprint)
    else:
        report = run(args.mode, dataset, fingerprint, top_k)
    output = args.output or ROOT / "evaluation" / "reports" / args.mode
    write_report(report, output)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("Reports:", output.with_suffix(".json"), output.with_suffix(".md"))
    return 1 if report["summary"]["failed_cases"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
