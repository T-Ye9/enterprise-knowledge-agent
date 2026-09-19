"""真实 HTTP/模型/检索验收，并回到 PDF 验证来源对应的页。"""
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.api import app
from app.document_processing import extract_pdf


def main():
    records = []
    with TestClient(app) as http:
        identifier = http.post("/sessions").json()["session_id"]
        for question in ["出差回来后多久提交报销？", "那要提交哪些材料？", "你好，请介绍一下你自己。", "帮我计算 123 * 456"]:
            result = http.post("/chat", json={"message": question, "session_id": identifier})
            assert result.status_code == 200, result.text
            row = {"question": question, **result.json()}
            records.append(row)
            print(json.dumps(row, ensure_ascii=False, indent=2), flush=True)
        assert records[0]["sources"] == [{"document": "demo-company-policy.pdf", "page": 2}]
        assert records[1]["sources"] == records[0]["sources"]
        assert records[2]["sources"] == records[3]["sources"] == []
        assert any(call["name"] == "calculator" for call in records[3]["tool_calls"])
        for row in records[:2]:
            for source in row["sources"]:
                pages = extract_pdf(ROOT / "samples" / source["document"])
                page = pages[source["page"] - 1]
                assert page["metadata"]["page_number"] == source["page"]
                assert "发票及费用说明" in page["text"] and "十个工作日" in page["text"]
        assert http.delete("/sessions/" + identifier).status_code == 204
    (ROOT / "samples" / "citation_examples.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: real citations match PDF page 2; chat/calculator have no sources", flush=True)


if __name__ == "__main__":
    main()
