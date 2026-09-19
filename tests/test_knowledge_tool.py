"""检索工具、Schema 及结果回传的离线测试。"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai.types.chat import ChatCompletionMessageToolCall

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.knowledge_tool import search_knowledge_base
from app.main import execute_tool, run_conversation
from app.tools import TOOL_DEFINITIONS


class KnowledgeToolTests(unittest.TestCase):
    def test_reuses_retrieval_and_preserves_metadata(self):
        embedder = Mock(model_name="test", dimension=2)
        store = Mock()
        metadata = {"source": "test.pdf", "page_number": 2, "chunk_id": "test.pdf:p2:c1", "custom": "keep"}
        retrieval = {"query": "报销？", "top_k": 2, "results": [{"score": 0.8, "text": "十个工作日", "metadata": metadata}]}
        with patch("app.embeddings.Embedder", return_value=embedder), patch("app.vector_store.VectorStore", return_value=store), patch("app.knowledge_base.search_query", return_value=retrieval) as search:
            result = search_knowledge_base("报销？", 2)
        search.assert_called_once_with("报销？", embedder, store, 2)
        store.close.assert_called_once()
        self.assertEqual(result["results"][0]["metadata"], metadata)
        self.assertEqual(result["results"][0]["citation"], metadata["chunk_id"])
        json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_closes_store_when_retrieval_fails(self):
        store = Mock()
        with patch("app.embeddings.Embedder"), patch("app.vector_store.VectorStore", return_value=store), patch("app.knowledge_base.search_query", side_effect=ValueError("test")):
            with self.assertRaises(ValueError):
                search_knowledge_base("问题")
        store.close.assert_called_once()

    def test_invalid_parameters(self):
        for arguments in ('{}', '[]', '{"query":" "}', '{"query":"x","top_k":0}', '{"query":"x","top_k":11}', '{"query":"x","top_k":true}', '{"query":"x","extra":1}'):
            with self.subTest(arguments=arguments):
                self.assertIn("error", execute_tool("search_knowledge_base", arguments))

    def test_dispatch_and_schema(self):
        with patch("app.tool_runtime.search_knowledge_base", return_value={"results": []}) as search:
            self.assertEqual(execute_tool("search_knowledge_base", '{"query":"报销？"}'), {"results": []})
        search.assert_called_once_with(query="报销？")
        definitions = {tool["function"]["name"]: tool["function"] for tool in TOOL_DEFINITIONS}
        self.assertEqual(set(definitions), {"calculator", "search_knowledge_base"})
        schema = definitions["search_knowledge_base"]["parameters"]
        self.assertEqual(schema["required"], ["query"])
        self.assertFalse(schema["additionalProperties"])

    def test_knowledge_result_sent_back_with_call_id(self):
        call = ChatCompletionMessageToolCall(id="search_call", type="function", function={"name": "search_knowledge_base", "arguments": '{"query":"报销？"}'})
        client = Mock()
        def response(content=None, calls=None):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))])
        client.chat.completions.create.side_effect = [response(calls=[call]), response("十个工作日[test.pdf:p2:c1]")]
        result = {"results": [{"text": "十个工作日", "metadata": {"source": "test.pdf", "page_number": 2, "chunk_id": "test.pdf:p2:c1"}}]}
        with patch("app.tool_runtime.search_knowledge_base", return_value=result), contextlib.redirect_stdout(io.StringIO()):
            trace = run_conversation(client, "test-model", "报销？")
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["tool_choice"], "auto")
        self.assertEqual(request["messages"][-1]["tool_call_id"], "search_call")
        self.assertEqual(json.loads(request["messages"][-1]["content"]), result)
        self.assertEqual(trace["tool_calls"][0]["result"], result)


if __name__ == "__main__":
    unittest.main()
