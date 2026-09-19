"""真实 LLM、检索工具、HTTP：同一会话连续三轮。仅使用公开虚构样例。"""
import json
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.api import app


def main():
    records = []
    with TestClient(app) as http:
        session_id = http.post("/sessions").json()["session_id"]
        for question in ["出差回来后，多久之内要提交报销？", "那要提交哪些材料？", "需要提前批准吗？"]:
            result = http.post("/chat", json={"session_id": session_id, "message": question})
            assert result.status_code == 200, result.text
            record = {"question": question, **result.json()}
            records.append(record)
            print(json.dumps(record, ensure_ascii=False, indent=2), flush=True)
            assert record["session_id"] == session_id
        assert re.search(r"(?:十|10)个工作日", records[0]["answer"])
        assert "发票" in records[1]["answer"]
        assert "批准" in records[2]["answer"]
        assert all("demo-company-policy.pdf:p2:c1" in row["answer"] for row in records)
        assert any(call["name"] == "search_knowledge_base" for call in records[0]["tool_calls"])
        # 后续轮可以再次检索，也可以使用历史中已有的工具证据，由 LLM 自主决定。
        assert http.delete("/sessions/" + session_id).status_code == 204
        assert http.post("/chat", json={"message": "继续", "session_id": session_id}).status_code == 404
    (ROOT / "samples" / "conversation_examples.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: three real conversation turns; session deleted", flush=True)


if __name__ == "__main__":
    main()
