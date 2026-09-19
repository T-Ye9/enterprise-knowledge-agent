"""确定性评分：只检查预先声明的事实，不声称证明整段答案真实。"""
import math
import re
import statistics

SCORER_VERSION = 2


def normalize(text):
    return re.sub(r"\s+", "", text).replace("**", "").replace(",", "").replace("，", "")


def source_key(metadata):
    return (metadata["source"], metadata["page_number"])


def fact_covered(fact, chunks):
    return any(source_key(chunk["metadata"]) == (fact["document"], fact["page"])
               and normalize(fact["quote"]) in normalize(chunk["text"]) for chunk in chunks)


def agent_chunks(trace):
    return [chunk for call in trace.get("tool_calls", []) if call["name"] == "search_knowledge_base"
            for chunk in call["result"].get("results", [])]


def score_case(case, record, agent_mode):
    facts = case.get("facts", [])
    baseline = record.get("retrieval", {}).get("results", [])
    expected_sources = {(f["document"], f["page"]) for f in facts}
    baseline_sources = {source_key(c["metadata"]) for c in baseline}
    checks = {}
    if "search_knowledge_base" in case["expected_tools"]:
        checks["retrieval_completed"] = "retrieval" in record and not record.get("retrieval_error")
    if facts:
        checks["retrieval_source_hit"] = bool(expected_sources & baseline_sources)
        checks["retrieval_all_sources"] = expected_sources <= baseline_sources
        checks["retrieval_evidence_coverage"] = all(fact_covered(f, baseline) for f in facts)
    if agent_mode:
        trace = record.get("trace", {})
        calls = trace.get("tool_calls", [])
        answer = normalize(trace.get("final_answer", ""))
        checks["agent_completed"] = bool(answer) and not record.get("agent_error")
        checks["tool_selection"] = {c["name"] for c in calls} == set(case["expected_tools"])
        chunks = agent_chunks(trace)
        cited = [(s["document"], s["page"]) for s in trace.get("sources", [])]
        cited_ids = set(re.findall(r"\[([^\[\]]+\.pdf:p\d+:c\d+)\]", trace.get("final_answer", "")))
        cited_chunks = [c for c in chunks if c["metadata"]["chunk_id"] in cited_ids]
        if facts:
            actual_sources = {source_key(c["metadata"]) for c in chunks}
            checks["agent_all_sources_retrieved"] = expected_sources <= actual_sources
            checks["citation_integrity"] = bool(cited) and bool(cited_ids) and cited_ids <= {c["metadata"]["chunk_id"] for c in chunks} and set(cited) <= actual_sources and len(cited) == len(set(cited))
            # 三个条件都检查：预期事实出现、对应原文实际被检索、对应来源被引用。
            checks["answer_evidence_check"] = all(re.search(f["answer_pattern"], answer, re.DOTALL) is not None
                                                   and fact_covered(f, cited_chunks) for f in facts) and expected_sources <= set(cited)
            if case.get("min_retrieved_chunks"):
                checks["multi_chunk_count"] = len({c["metadata"]["chunk_id"] for c in chunks}) >= case["min_retrieved_chunks"]
        if case.get("refusal"):
            quantity = r"(?:\d+|[一二三四五六七八九十百千两]+)(?:元|万元|个月|天|%)|百分之(?:\d+|[一二三四五六七八九十百千两]+)"
            quantities = re.findall(quantity, answer)
            supported = all(any(value in normalize(c["text"]) for c in cited_chunks) for value in quantities)
            checks["unsupported_refusal"] = "没有足够依据" in answer and supported
        if "expected_calculation" in case:
            expected = case["expected_calculation"]
            checks["calculator_result"] = any(c["name"] == "calculator" and c["result"].get("result") == expected for c in calls)
            checks["calculator_answer"] = re.search(rf"(?<!\d){expected}(?!\d)", answer) is not None
        if case["category"] in {"calculator", "chat"}:
            checks["no_document_sources"] = cited == []
        if record.get("agent_error"):
            # 运行异常不能因为空工具集合恰好等于 chat 预期而算成功。
            checks = {name: value if name.startswith("retrieval_") else False for name, value in checks.items()}
    if record.get("retrieval_error"):
        for name in list(checks):
            if name.startswith("retrieval_"):
                checks[name] = False
    return checks


def summarize(rows):
    names = sorted({name for row in rows for name in row["checks"]})
    metrics = {}
    for name in names:
        values = [row["checks"][name] for row in rows if name in row["checks"]]
        metrics[name] = {"passed": sum(values), "total": len(values), "rate": sum(values) / len(values)}
    latency = {}
    for kind in ["retrieval", "agent"]:
        values = sorted(row[f"{kind}_seconds"] for row in rows if row.get(f"{kind}_seconds") is not None)
        if values:
            latency[kind] = {"count": len(values), "p50_seconds": statistics.median(values),
                             "p95_seconds": values[math.ceil(.95 * len(values)) - 1]}
    return {"metrics": metrics, "latency": latency,
            "failed_cases": [row["id"] for row in rows if not all(row["checks"].values())]}
