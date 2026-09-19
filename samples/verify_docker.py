"""对已启动的 Compose 服务验收；仅上传公开样例，不打印业务正文。"""
import argparse
import json
import time
from pathlib import Path

import httpx


def verify(base_url):
    started = time.perf_counter()
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=180) as http:
        response = http.get("/")
        response.raise_for_status()
        assert 'id="root"' in response.text, "前端入口没有 React root"
        assert http.get("/api/health").json() == {"status": "ok"}
        print("PASS: frontend + proxied health")
        # 明确检查参数错误通过反向代理后仍是 JSON 422。
        invalid = http.post("/api/chat", json={"message": " "})
        assert invalid.status_code == 422
        print("PASS: request validation")
        calculation = http.post("/api/chat", json={"message": "帮我计算 123 * 456"})
        calculation.raise_for_status()
        reply = calculation.json()
        assert any(call["name"] == "calculator" and call["result"].get("result") == 56088
                   for call in reply["tool_calls"])
        assert "56088" in reply["answer"] and reply["sources"] == []
        print("PASS: real calculator + LLM")
        pdf = Path(__file__).resolve().parent / "web-demo-policy.pdf"
        with pdf.open("rb") as file:
            upload = http.post("/api/documents", files={"file": (pdf.name, file, "application/pdf")})
        upload.raise_for_status()
        document = upload.json()["document"]
        assert upload.json()["chunks_saved"] > 0
        print("PASS: real PDF ingestion + embedding + vector store")
        done = None
        deltas = 0
        with http.stream("POST", "/api/chat/stream", json={"message": "Project Cedar 每位员工每月健康补贴是多少元？"}) as stream:
            stream.raise_for_status()
            assert "text/event-stream" in stream.headers.get("content-type", "")
            event = None
            for line in stream.iter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                    assert event != "error", "流式服务返回 error（请检查安全日志）"
                    if event == "delta":
                        deltas += 1
                    if event == "done":
                        done = data
        assert done is not None and deltas > 0
        assert "731" in done["answer"]
        # 重复验收会有同内容的旧上传，引用任何实际命中的公开副本都有效。
        assert any(source["document"].startswith("web-demo-policy--") and source["page"] == 1
                   for source in done["sources"])
        assert any(call["name"] == "search_knowledge_base" for call in done["tool_calls"])
        actual_sources = {(chunk["metadata"]["source"], chunk["metadata"]["page_number"])
                          for call in done["tool_calls"] if call["name"] == "search_knowledge_base"
                          for chunk in call["result"].get("results", [])}
        assert all((source["document"], source["page"]) in actual_sources for source in done["sources"])
        print("PASS: SSE + real knowledge tool + source page")
        for identifier in (reply["session_id"], done["session_id"]):
            assert http.delete(f"/api/sessions/{identifier}").status_code == 204
    print(f"PASS: Docker HTTP flow ({time.perf_counter() - started:.1f}s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    verify(args.url)
