"""1GiB Linux 容器验收；只使用本脚本专属的测试容器与公开 Demo。"""
import json
import os
import threading
import time
from pathlib import Path

import httpx

from validate_memory import ROOT, docker, inventory, state


NAME = "eka-1g-validation-backend"
WEB_NAME = "eka-1g-validation-frontend"
NETWORK = "eka-1g-validation-network"
BASE = "http://127.0.0.1:18011"
WEB = "http://127.0.0.1:18096"
REPORT = ROOT / "output" / "deployment-validation" / "report-1g.json"
LIMIT = 1024 * 1024 * 1024


def reading():
    lines = docker("exec", NAME, "sh", "-c",
                   "cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak "
                   "/sys/fs/cgroup/memory.events /sys/fs/cgroup/cpu.stat").splitlines()
    stats = {}
    for line in lines[2:]:
        key, value = line.split()
        stats[key] = int(value)
    return {"current_bytes": int(lines[0]), "kernel_peak_bytes": int(lines[1]),
            "events": {key: stats[key] for key in ("max", "oom", "oom_kill")},
            "cpu_usage_usec": stats["usage_usec"],
            "cpu_throttled_usec": stats.get("throttled_usec", 0)}


class Sampler:
    def __init__(self):
        self.phase = "startup"
        self.values = []
        self.stop = threading.Event()
        self.worker = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop.is_set():
            try:
                self.values.append({"phase": self.phase, "time": time.monotonic(), **reading()})
            except RuntimeError:
                pass  # 启动/重启间隙 exec 不可用；随后检查容器状态。
            self.stop.wait(0.2)

    def start(self):
        self.worker.start()

    def finish(self):
        self.stop.set()
        self.worker.join(timeout=5)

    def max_current(self, phase):
        values = [item["current_bytes"] for item in self.values if item["phase"] == phase]
        return max(values, default=None)


def ready(timeout=600):
    start = time.monotonic()
    with httpx.Client(timeout=3) as client:
        while time.monotonic() - start < timeout:
            if not state(NAME)["Running"]:
                raise RuntimeError("后端启动期间退出")
            try:
                response = client.get(BASE + "/health")
                if response.status_code == 200 and response.json() == {"status": "ok"}:
                    return round(time.monotonic() - start, 2)
            except httpx.HTTPError:
                pass
            time.sleep(1)
    raise TimeoutError("后端 600 秒内未就绪")


def check_sources(body, previous_retrievals=()):
    actual = {(chunk["metadata"]["source"], chunk["metadata"]["page_number"])
              for call in body["tool_calls"] if call["name"] == "search_knowledge_base"
              for chunk in call["result"].get("results", [])}
    actual.update((source["document"], source["page"]) for source in previous_retrievals)
    assert all((source["document"], source["page"]) in actual for source in body["sources"])
    return [{"document": document, "page": page} for document, page in sorted(actual)]


def run_chat(client, message, tool=None, text=None, source=None, session=None, previous_retrievals=()):
    payload = {"message": message}
    if session:
        payload["session_id"] = session
    response = client.post(BASE + "/chat", json=payload)
    response.raise_for_status()
    body = response.json()
    tools = [call["name"] for call in body["tool_calls"]]
    if tool is None:
        assert not tools
        assert not body["sources"]
    elif tool != "any":
        assert tool in tools
    if text:
        assert any(item in body["answer"] for item in text)
    if source:
        assert source in body["sources"]
    retrieved_sources = check_sources(body, previous_retrievals)
    return {"status": response.status_code, "tools": tools, "sources": body["sources"],
            "session_id": body["session_id"], "retrieved_sources": retrieved_sources,
            "answer": body["answer"]}


def run_stream(client):
    events = []
    with client.stream("POST", WEB + "/api/chat/stream",
                       json={"message": "Project Cedar 每位员工每月健康补贴是多少元？"}) as response:
        response.raise_for_status()
        assert "text/event-stream" in response.headers["content-type"]
        event = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                events.append((event, json.loads(line[6:])))
    assert events and events[-1][0] == "done"
    assert sum(event == "delta" for event, _ in events) > 0
    assert not any(event == "error" for event, _ in events)
    done = events[-1][1]
    assert "731" in done["answer"]
    assert {"document": "web-demo-policy.pdf", "page": 1} in done["sources"]
    assert any(call["name"] == "search_knowledge_base" for call in done["tool_calls"])
    check_sources(done)
    return {"status": 200, "tools": [call["name"] for call in done["tool_calls"]],
            "sources": done["sources"], "delta_count": sum(event == "delta" for event, _ in events),
            "events": [event for event, _ in events], "answer": done["answer"]}


def checked_call(report, sampler, client, label, fn):
    sampler.phase = label
    before = reading()
    started = time.monotonic()
    result = fn()
    elapsed = time.monotonic() - started
    after = reading()
    assert after["events"] == before["events"]
    assert state(NAME)["Running"]
    cpu_seconds = (after["cpu_usage_usec"] - before["cpu_usage_usec"]) / 1_000_000
    report["requests"].append({"label": label, "seconds": round(elapsed, 2),
                               "sampled_peak_bytes": sampler.max_current(label),
                               "lifetime_kernel_peak_after_bytes": after["kernel_peak_bytes"],
                               "cpu_seconds": round(cpu_seconds, 3),
                               "average_cpu_percent_of_one_core": round(100 * cpu_seconds / elapsed, 1),
                               **result})
    print("PASS", len(report["requests"]), label, flush=True)
    return result


def main():
    from app.llm_client import read_configuration

    key, url, model = read_configuration()
    os.environ.update(DEEPSEEK_API_KEY=key, DEEPSEEK_BASE_URL=url, DEEPSEEK_MODEL=model)
    report = {"status": "in_progress", "limit_bytes": LIMIT, "extra_swap_bytes": 0,
              "cpu_limit": "none", "persistent_volumes": False, "requests": []}
    created = []
    sampler = None
    try:
        docker("network", "create", NETWORK)
        docker("run", "-d", "--name", NAME, "--label", "purpose=eka-1g-validation",
               "--network", NETWORK, "--network-alias", "backend", "--memory", "1g",
               "--memory-swap", "1g", "--restart", "no",
               "-e", "DEEPSEEK_API_KEY", "-e", "DEEPSEEK_BASE_URL", "-e", "DEEPSEEK_MODEL",
               "-e", "APP_ENV=production", "-e", "ALLOW_DOCUMENT_UPLOAD=false",
               "-e", "CORS_ORIGINS=", "-e", "PORT=8000",
               "-e", "KNOWLEDGE_DB_PATH=/app/data/vector-db",
               "-e", "EMBEDDING_CACHE_DIR=/app/.cache/embeddings",
               "-e", "BOOTSTRAP_DEMO_KNOWLEDGE_BASE=true",
               "-p", "127.0.0.1:18011:8000", "knowledge-agent-memory:backend")
        created.append(NAME)
        sampler = Sampler()
        sampler.start()
        report["cold_start_seconds"] = ready()
        report["initialization_end"] = reading()
        report["initialization_peak_bytes"] = report["initialization_end"]["kernel_peak_bytes"]
        assert docker("inspect", "--format", "{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}", NAME) == f"{LIMIT} {LIMIT}"
        assert docker("inspect", "--format", "{{.RestartCount}}", NAME) == "0"
        sampler.phase = "idle"
        time.sleep(5)
        report["idle"] = reading()
        report["chunk_count"] = inventory(NAME)
        assert report["chunk_count"] == 3

        docker("run", "-d", "--name", WEB_NAME, "--label", "purpose=eka-1g-validation",
               "--network", NETWORK, "-p", "127.0.0.1:18096:80",
               "knowledge-agent-memory:frontend")
        created.append(WEB_NAME)
        with httpx.Client(timeout=180) as client:
            for _ in range(30):
                try:
                    page = client.get(WEB + "/")
                    if page.status_code == 200 and 'id="root"' in page.text:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("前端未就绪")
            assert client.get(WEB + "/api/health").json() == {"status": "ok"}
            report["health_and_frontend"] = "passed"

            checked_call(report, sampler, client, "ordinary", lambda: run_chat(client, "你好，请介绍一下你自己。"))
            checked_call(report, sampler, client, "calculator", lambda: run_chat(client, "帮我计算 123 * 456", "calculator", ["56088"]))
            checked_call(report, sampler, client, "knowledge", lambda: run_chat(client, "Project Cedar 每位员工每月健康补贴是多少元？", "search_knowledge_base", ["731"], {"document": "web-demo-policy.pdf", "page": 1}))
            checked_call(report, sampler, client, "rag_page2", lambda: run_chat(client, "差旅报销要提交什么材料？", "search_knowledge_base", ["发票"], {"document": "demo-company-policy.pdf", "page": 2}))
            checked_call(report, sampler, client, "rag_two_pages", lambda: run_chat(client, "公司工作时间和差旅报销期限分别是什么？", "search_knowledge_base", ["十", "10"], {"document": "demo-company-policy.pdf", "page": 2}))
            checked_call(report, sampler, client, "unsupported", lambda: run_chat(client, "公司 CEO 的私人银行卡号是多少？仅依据知识库回答。", "search_knowledge_base", ["没有", "不足", "无法"]))

            first = checked_call(report, sampler, client, "conversation_1", lambda: run_chat(client, "公司差旅报销需要提交哪些材料？", "search_knowledge_base", ["发票"], {"document": "demo-company-policy.pdf", "page": 2}))
            session = first["session_id"]
            second = checked_call(report, sampler, client, "conversation_2", lambda: run_chat(client, "那要在多久内提交？", "any", ["十", "10"], session=session, previous_retrievals=first["retrieved_sources"]))
            third = checked_call(report, sampler, client, "conversation_3", lambda: run_chat(client, "出差之前还需要做什么？", "any", ["主管", "批准", "审批"], session=session, previous_retrievals=second["retrieved_sources"]))
            assert second["session_id"] == third["session_id"] == session
            checked_call(report, sampler, client, "sse", lambda: run_stream(client))
            checked_call(report, sampler, client, "calculator_repeat", lambda: run_chat(client, "帮我计算 999 + 888", "calculator", ["1887"]))
            report["runtime_end"] = reading()
            report["runtime_restart_count"] = int(docker("inspect", "--format", "{{.RestartCount}}", NAME))
            assert report["runtime_restart_count"] == 0
            assert report["runtime_end"]["events"] == {"max": 0, "oom": 0, "oom_kill": 0}
            assert state(NAME)["Health"]["Status"] == "healthy"

        sampler.phase = "recovery"
        # 固定路径仅位于本轮脚本创建的测试容器；不删除主机现有知识库。
        docker("exec", NAME, "python", "-c", "import shutil; shutil.rmtree('/app/data/vector-db')")
        docker("restart", NAME)
        report["recovery_seconds"] = ready()
        report["recovered_chunks"] = inventory(NAME)
        assert report["recovered_chunks"] == 3
        with httpx.Client(timeout=180) as client:
            report["recovery_request"] = run_chat(client, "Project Cedar 每月健康补贴是多少元？", "search_knowledge_base", ["731"], {"document": "web-demo-policy.pdf", "page": 1})
        report["planned_restart_count"] = int(docker("inspect", "--format", "{{.RestartCount}}", NAME))
        report["recovery_end"] = reading()
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["failure_type"] = type(error).__name__
        print("VALIDATION FAILED:", type(error).__name__, flush=True)
        raise
    finally:
        if sampler:
            sampler.finish()
            report["samples"] = sampler.values
            report["per_request_sampled_peaks"] = {
                item["label"]: sampler.max_current(item["label"]) for item in report["requests"]}
        report["container_states"] = {name: state(name) for name in created}
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Report saved:", REPORT, flush=True)


if __name__ == "__main__":
    main()
