"""通过 FastAPI TestClient 执行真实模型、真实图和真实工具验收。"""

import json
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.api import app


def main():
    results = []
    with TestClient(app) as http:
        assert http.get("/health").json() == {"status": "ok"}
        for question in [
            "你好，请介绍一下你自己。", "帮我计算 123 * 456",
            "出差回来后，多久之内要提交报销？", "公司员工每年的年终奖金是多少元？",
        ]:
            response = http.post("/chat", json={"message": question})
            print("HTTP Status:", response.status_code, flush=True)
            assert response.status_code == 200, response.text
            result = {"question": question, **response.json()}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    (ROOT / "samples" / "agent_examples.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    assert results[0]["path"] == ["START", "agent", "END"]
    assert results[0]["tool_calls"] == []
    assert {call["name"] for call in results[1]["tool_calls"]} == {"calculator"}
    assert any(call["result"] == {"result": 56088} for call in results[1]["tool_calls"])
    assert "56088" in results[1]["answer"].replace(",", "")
    for index in (2, 3):
        assert {call["name"] for call in results[index]["tool_calls"]} == {"search_knowledge_base"}
        assert "tools" in results[index]["path"]
        assert all("results" in call["result"] for call in results[index]["tool_calls"])
    assert re.search(r"(?:十|10)个工作日", results[2]["answer"])
    assert "demo-company-policy.pdf:p2:c1" in results[2]["answer"]
    assert "没有足够依据" in results[3]["answer"]
    print("PASS: four real API → LangGraph Agent workflows", flush=True)


if __name__ == "__main__":
    main()
