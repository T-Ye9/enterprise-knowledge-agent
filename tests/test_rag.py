"""离线测试上下文传递与来源，不代替真实问答效果验收。"""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.rag import INSUFFICIENT_ANSWER, RAG_SYSTEM_PROMPT, run_rag


class RAGTests(unittest.TestCase):
    def setUp(self):
        self.embedder = Mock(model_name="test-model")
        self.embedder.embed_query.return_value = [1., 0.]
        self.store = Mock()
        self.hit = {"score": 0.8, "text": "报销期限：十个工作日。", "metadata": {
            "source": "test.pdf", "page_number": 2, "chunk_id": "test.pdf:p2:c1",
        }}
        self.store.search.return_value = [self.hit]
        self.client = Mock()
        self.set_answer("十个工作日内提交。[1]")

    def set_answer(self, text, calls=None):
        self.client.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=calls))
        ])

    def test_context_sources_and_retrieval_reuse(self):
        result = run_rag("报销期限？", self.embedder, self.store, self.client, "llm", 2)
        self.embedder.embed_query.assert_called_once_with("报销期限？")
        self.store.search.assert_called_once_with([1., 0.], 2)
        request = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["messages"][0]["content"], RAG_SYSTEM_PROMPT)
        sent = json.loads(request["messages"][1]["content"])
        self.assertEqual(sent["question"], "报销期限？")
        self.assertEqual(sent["retrieved_context"][0]["text"], self.hit["text"])
        self.assertEqual(sent["retrieved_context"][0]["metadata"], self.hit["metadata"])
        self.assertEqual(result["retrieved_chunks"], [self.hit])
        self.assertEqual(result["sources"][0]["metadata"], self.hit["metadata"])
        self.assertNotIn("tools", request)
        self.client.chat.completions.create.assert_called_once()

    def test_no_results_refuses_without_llm(self):
        self.store.search.return_value = []
        result = run_rag("不存在的问题", self.embedder, self.store, self.client, "llm")
        self.assertEqual(result["answer"], INSUFFICIENT_ANSWER)
        self.assertEqual(result["sources"], [])
        self.client.chat.completions.create.assert_not_called()

    def test_invalid_question_or_top_k(self):
        for question, k in [(" ", 3), ("问题", 0), ("问题", True)]:
            with self.subTest(question=question, k=k), self.assertRaises(ValueError):
                run_rag(question, self.embedder, self.store, self.client, "llm", k)
        self.client.chat.completions.create.assert_not_called()

    def test_invalid_answer_or_citation(self):
        for answer in ("", "没有依据[9]", "引用[0]"):
            self.set_answer(answer)
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                run_rag("报销期限？", self.embedder, self.store, self.client, "llm")

    def test_multiple_chunks_have_separate_citations(self):
        second = {"score": 0.7, "text": "休假提前三个工作日申请。", "metadata": {
            "source": "test.pdf", "page_number": 1, "chunk_id": "test.pdf:p1:c1",
        }}
        self.store.search.return_value = [self.hit, second]
        self.set_answer("休假提前三个工作日[2]，报销十个工作日[1]。")
        result = run_rag("休假和报销？", self.embedder, self.store, self.client, "llm")
        self.assertEqual([source["citation"] for source in result["sources"]], ["[1]", "[2]"])
        self.assertEqual(len(json.loads(result["context"])), 2)


if __name__ == "__main__":
    unittest.main()
