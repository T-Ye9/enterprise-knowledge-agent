"""检查评分器会拒绝错误来源/错误工具/假拒答，不调用 LLM。"""
import unittest

from evaluation.metrics import score_case, summarize
from evaluation.run import load_dataset, replay
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case = {"id": "test", "category": "knowledge", "expected_tools": ["search_knowledge_base"],
                     "facts": [{"document": "test.pdf", "page": 2, "quote": "十个工作日", "answer_pattern": "(?:十|10)个工作日"}]}
        self.chunk = {"text": "报销期限十个工作日", "metadata": {"source": "test.pdf", "page_number": 2, "chunk_id": "test.pdf:p2:c1"}}
        self.record = {"retrieval": {"results": [self.chunk]}, "trace": {
            "final_answer": "10 个工作日[test.pdf:p2:c1]", "sources": [{"document": "test.pdf", "page": 2}],
            "tool_calls": [{"name": "search_knowledge_base", "result": {"results": [self.chunk]}}]}}

    def test_correct_fact_and_actual_citation_pass(self):
        self.assertTrue(all(score_case(self.case, self.record, True).values()))

    def test_right_keywords_with_wrong_cited_chunk_do_not_pass(self):
        wrong = {"text": "周一至周五工作", "metadata": {"source": "test.pdf", "page_number": 1, "chunk_id": "test.pdf:p1:c1"}}
        self.record["trace"]["tool_calls"][0]["result"]["results"].append(wrong)
        self.record["trace"]["final_answer"] = "十个工作日[test.pdf:p1:c1]"
        self.record["trace"]["sources"] = [{"document": "test.pdf", "page": 1}]
        checks = score_case(self.case, self.record, True)
        self.assertTrue(checks["citation_integrity"])
        self.assertFalse(checks["answer_evidence_check"])

    def test_correct_source_but_missing_evidence_fails(self):
        self.record["retrieval"]["results"] = [{**self.chunk, "text": "没有报销期限"}]
        checks = score_case(self.case, self.record, False)
        self.assertTrue(checks["retrieval_all_sources"])
        self.assertFalse(checks["retrieval_evidence_coverage"])

    def test_wrong_tool_and_error_cannot_count_as_success(self):
        self.record["trace"]["tool_calls"] = [{"name": "calculator", "result": {"result": 10}}]
        self.assertFalse(score_case(self.case, self.record, True)["tool_selection"])
        chat = {"category": "chat", "expected_tools": []}
        self.assertFalse(any(score_case(chat, {"agent_error": "Timeout"}, True).values()))

    def test_agent_error_does_not_erase_independent_retrieval_score(self):
        self.record["agent_error"] = "Timeout"
        checks = score_case(self.case, self.record, True)
        self.assertTrue(checks["retrieval_all_sources"])
        self.assertTrue(checks["retrieval_evidence_coverage"])
        self.assertFalse(checks["agent_completed"])
        self.assertFalse(checks["tool_selection"])

    def test_refusal_with_fabricated_amount_or_ratio_fails(self):
        case = {"category": "unsupported", "expected_tools": ["search_knowledge_base"], "refusal": True}
        for answer, expected in [("知识库中没有足够依据回答这个问题。", True),
                                 ("没有足够依据，但年终奖固定5000元。", False),
                                 ("没有足够依据，但比例是百分之八十。", False), ("有五天年假", False)]:
            record = {"trace": {"final_answer": answer}}
            self.assertEqual(score_case(case, record, True)["unsupported_refusal"], expected)

    def test_refusal_can_explain_with_actual_cited_quantity(self):
        case = {"category": "unsupported", "expected_tools": ["search_knowledge_base"], "refusal": True}
        chunk = {"text": "健康补贴731元", "metadata": {"source": "test.pdf", "page_number": 1, "chunk_id": "test.pdf:p1:c1"}}
        record = {"trace": {"final_answer": "没有足够依据说明年终奖。只有健康补贴731元[test.pdf:p1:c1]",
            "tool_calls": [{"name": "search_knowledge_base", "result": {"results": [chunk]}}]}}
        self.assertTrue(score_case(case, record, True)["unsupported_refusal"])
        record["trace"]["final_answer"] = "没有足够依据，但奖金5000元[test.pdf:p1:c1]"
        self.assertFalse(score_case(case, record, True)["unsupported_refusal"])
        record["trace"]["final_answer"] = "没有足够依据。只有健康补贴731元"
        self.assertFalse(score_case(case, record, True)["unsupported_refusal"])

    def test_denominators_exclude_non_applicable_cases_and_latency(self):
        rows = [{"id": "known", "checks": {"retrieval_source_hit": True}, "retrieval_seconds": 1},
                {"id": "chat", "checks": {"tool_selection": False}, "agent_seconds": 3}]
        summary = summarize(rows)
        self.assertEqual(summary["metrics"]["retrieval_source_hit"]["total"], 1)
        self.assertEqual(summary["failed_cases"], ["chat"])
        self.assertEqual(summary["latency"]["agent"]["p95_seconds"], 3)

    def test_dataset_gold_quotes_exist_and_replay_rejects_changed_hash(self):
        dataset, fingerprint = load_dataset()
        self.assertEqual(len(dataset["cases"]), 19)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "old.json"
            path.write_text(json.dumps({**fingerprint, "dataset_sha256": "changed"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "变更"):
                replay(path, dataset, fingerprint)

    def test_replay_scores_are_repeatable_without_model_calls(self):
        case = {"id": "U", "category": "unsupported", "expected_tools": ["search_knowledge_base"], "refusal": True}
        fingerprint = {"dataset_sha256": "dataset", "corpus_sha256": {"test.pdf": "pdf"}}
        row = {"id": "U", "category": "unsupported", "retrieval": {"results": []},
               "trace": {"final_answer": "知识库中没有足够依据回答这个问题。",
                         "tool_calls": [{"name": "search_knowledge_base", "result": {"results": []}}]}}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            path.write_text(json.dumps({**fingerprint, "mode": "agent", "created_at": "original", "cases": [row]}), encoding="utf-8")
            with patch("app.llm_client.create_client", side_effect=AssertionError("不应调用模型")):
                first = replay(path, {"cases": [case]}, fingerprint)
                second = replay(path, {"cases": [case]}, fingerprint)
        self.assertEqual(first["summary"], second["summary"])
        self.assertEqual(first["cases"][0]["checks"], second["cases"][0]["checks"])


if __name__ == "__main__":
    unittest.main()
