"""四类真实原生 Tool Calling 验收，使用已有公开样本库。"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.llm_client import create_client
from app.main import run_conversation


def main():
    client, model = create_client()
    traces = []
    try:
        for question in [
            "帮我计算 123 * 456",
            "出差回来后，多久之内要提交报销？",
            "你好，请介绍一下你自己。",
            "公司员工每年的年终奖金是多少元？",
        ]:
            traces.append(run_conversation(client, model, question))
    finally:
        client.close()
    (ROOT / "samples" / "knowledge_tool_examples.json").write_text(
        json.dumps(traces, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    assert {call["name"] for call in traces[0]["tool_calls"]} == {"calculator"}
    assert any(call["result"] == {"result": 56088} for call in traces[0]["tool_calls"])
    assert "56088" in traces[0]["final_answer"].replace(",", "")
    for index in (1, 3):
        assert {call["name"] for call in traces[index]["tool_calls"]} == {"search_knowledge_base"}
        for call in traces[index]["tool_calls"]:
            assert "results" in call["result"]
            for hit in call["result"]["results"]:
                assert {"source", "page_number", "chunk_id"} <= set(hit["metadata"])
    assert re.search(r"(?:十|10)个工作日", traces[1]["final_answer"])
    assert "demo-company-policy.pdf:p2:c1" in traces[1]["final_answer"]
    assert traces[2]["tool_calls"] == []
    assert traces[2]["final_answer"]
    assert "没有足够依据" in traces[3]["final_answer"]
    print("PASS: calculator / knowledge search / direct chat / unsupported knowledge question")


if __name__ == "__main__":
    main()
