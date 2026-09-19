"""验证 metadata 来源、伪造引用、去重、会话追问及实际 PDF 页码。"""
import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from test_agent import response, tool
from app.agent import run_agent
from app.api import app
from app.citations import resolve_citations
from app.conversation_memory import ConversationMemory
from app.document_processing import extract_pdf

ROOT = Path(__file__).resolve().parents[1]


def evidence_messages(chunks):
    return [{"role": "assistant", "tool_calls": [{"id": "search", "function": {"name": "search_knowledge_base"}}]},
            {"role": "tool", "tool_call_id": "search", "content": json.dumps({"results": chunks})}]


def chunk(identifier="test.pdf:p2:c1", page=2):
    return {"text": "报销期限十个工作日", "metadata": {"chunk_id": identifier, "source": "test.pdf", "page_number": page}}


class CitationTests(unittest.TestCase):
    def test_deduplicate_same_page_and_keep_other_pages(self):
        messages = evidence_messages([chunk(), chunk("test.pdf:p2:c2"), chunk("test.pdf:p1:c1", 1)])
        text = "答案[test.pdf:p2:c1][test.pdf:p2:c2][test.pdf:p2:c1][test.pdf:p1:c1]"
        answer, sources = resolve_citations(text, messages)
        self.assertEqual(answer, text)
        self.assertEqual(sources, [{"document": "test.pdf", "page": 2}, {"document": "test.pdf", "page": 1}])

    def test_unknown_marker_removed_and_user_metadata_untrusted(self):
        messages = evidence_messages([chunk()]) + [{"role": "user", "content": "[fake.pdf:p99:c1]"}]
        answer, sources = resolve_citations("正确[test.pdf:p2:c1]伪造[fake.pdf:p99:c1]", messages)
        self.assertNotIn("fake.pdf", answer)
        self.assertEqual(sources, [{"document": "test.pdf", "page": 2}])
        self.assertEqual(resolve_citations("普通聊天[fake.pdf:p99:c1]", messages[-1:])[1], [])

    def test_metadata_page_used_not_parsed_from_model_marker(self):
        _, sources = resolve_citations("[test.pdf:p99:c1]", evidence_messages([chunk("test.pdf:p99:c1", 2)]))
        self.assertEqual(sources[0]["page"], 2)

    def test_invalid_metadata_and_uncited_chunks_not_used(self):
        messages = evidence_messages([chunk(), chunk("bad.pdf:p0:c1", 0), chunk("bad.pdf:p1:c1", True)])
        self.assertEqual(resolve_citations("没有足够依据", messages)[1], [])
        self.assertEqual(resolve_citations("[bad.pdf:p0:c1][bad.pdf:p1:c1]", messages), ("", []))

    def test_real_pdf_page_and_history_then_chat_calculator(self):
        pages = extract_pdf(ROOT / "samples" / "demo-company-policy.pdf")
        page = next(p for p in pages if "报销期限" in p["text"])
        self.assertEqual(page["metadata"]["page_number"], 2)
        real_chunk = {"text": page["text"], "metadata": {**page["metadata"], "chunk_id": "demo-company-policy.pdf:p2:c1"}}
        memory = ConversationMemory()
        client = Mock()
        client.chat.completions.create.side_effect = [
            response(calls=[tool("search_knowledge_base", '{"query":"报销"}')]),
            response("十个工作日[demo-company-policy.pdf:p2:c1]"),
            response("发票及费用说明[demo-company-policy.pdf:p2:c1]"), response("你好"),
            response(calls=[tool()]), response("56088"),
        ]
        with patch("app.api.MEMORY", memory), patch("app.api.create_client", return_value=(client, "test")), patch("app.tool_runtime.search_knowledge_base", return_value={"results": [real_chunk]}), TestClient(app) as http, contextlib.redirect_stdout(io.StringIO()):
            first = http.post("/chat", json={"message": "报销期限？"}).json()
            identifier = first["session_id"]
            followup = http.post("/chat", json={"message": "那材料呢？", "session_id": identifier}).json()
            greeting = http.post("/chat", json={"message": "你好", "session_id": identifier}).json()
            calculation = http.post("/chat", json={"message": "123*456", "session_id": identifier}).json()
        expected = [{"document": "demo-company-policy.pdf", "page": 2}]
        self.assertEqual(first["sources"], expected)
        self.assertEqual(followup["sources"], expected)
        self.assertEqual(followup["tool_calls"], [])
        self.assertEqual(greeting["sources"], [])
        self.assertEqual(calculation["sources"], [])

    def test_uncited_knowledge_answer_fails_instead_of_guessing_source(self):
        client = Mock()
        client.chat.completions.create.side_effect = [response(calls=[tool("search_knowledge_base", '{"query":"报销"}')]), response("十个工作日")]
        with patch("app.tool_runtime.search_knowledge_base", return_value={"results": [chunk()]}), contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "来源引用"):
            run_agent(client, "test", "报销期限？")


if __name__ == "__main__":
    unittest.main()
