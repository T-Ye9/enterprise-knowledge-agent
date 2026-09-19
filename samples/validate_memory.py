"""真实 Linux/512MiB 验证；只操作本脚本创建的容器，不打印环境变量。"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPORT = ROOT / "output" / "deployment-validation" / "report.json"
PREFIX = "eka-memory-validation"
BACKEND = PREFIX + "-backend"
FRONTEND = PREFIX + "-frontend"
NETWORK = PREFIX + "-network"
BASE = "http://127.0.0.1:18001"
WEB = "http://127.0.0.1:18086"


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    if result.returncode:
        # 不回显 Docker 命令或输出，避免环境配置出现在失败报告里。
        raise RuntimeError("Docker 操作失败: " + args[0])
    return result.stdout.strip()


def state(name):
    return json.loads(docker("inspect", "--format", "{{json .State}}", name))


def sample(name):
    raw = docker("exec", name, "sh", "-c",
                 "cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak "
                 "/sys/fs/cgroup/memory.events")
    lines = raw.splitlines()
    return {"current_bytes": int(lines[0]), "kernel_peak_bytes": int(lines[1]),
            "events": {key: int(value) for key, value in
                       (line.split() for line in lines[2:])}}


class Monitor:
    def __init__(self, name):
        self.name = name
        self.phase = "initialization"
        self.samples = []
        self.unavailable_samples = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.collect, daemon=True)

    def collect(self):
        while not self.stop.is_set():
            try:
                reading = sample(self.name)
                reading.update(phase=self.phase, elapsed_seconds=round(time.monotonic() - self.started, 2))
                self.samples.append(reading)
            except (RuntimeError, subprocess.TimeoutExpired):
                # Docker exec 在容器启动/退出边界不可用；最终还会检查容器退出状态。
                self.unavailable_samples += 1
            self.stop.wait(0.3)

    def start(self):
        self.started = time.monotonic()
        self.thread.start()

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=125)
        return self.samples


def wait_ready(name, timeout=600):
    started = time.monotonic()
    with httpx.Client(timeout=3) as client:
        while time.monotonic() - started < timeout:
            current = state(name)
            if not current["Running"]:
                raise RuntimeError("后端提前退出")
            try:
                response = client.get(BASE + "/health")
                if response.status_code == 200 and response.json() == {"status": "ok"}:
                    return round(time.monotonic() - started, 2)
            except httpx.HTTPError:
                pass
            time.sleep(1)
    raise TimeoutError("后端在 600 秒内未就绪")


def launch(name, bootstrap):
    docker("run", "-d", "--name", name, "--label", "purpose=eka-memory-validation",
           "--network", NETWORK, "--network-alias", "backend",
           "--memory", "512m", "--memory-swap", "512m",
           "-e", "DEEPSEEK_API_KEY", "-e", "DEEPSEEK_BASE_URL", "-e", "DEEPSEEK_MODEL",
           "-e", "APP_ENV=production", "-e", "ALLOW_DOCUMENT_UPLOAD=false",
           "-e", "CORS_ORIGINS=", "-e", "PORT=8000",
           "-e", "KNOWLEDGE_DB_PATH=/app/data/vector-db",
           "-e", "EMBEDDING_CACHE_DIR=/app/.cache/embeddings",
           "-e", "BOOTSTRAP_DEMO_KNOWLEDGE_BASE=" + str(bootstrap).lower(),
           "-p", "127.0.0.1:18001:8000", "knowledge-agent-memory:backend")


def chat(client, message, expected_tool, expected_text=None, expected_source=None):
    started = time.monotonic()
    response = client.post(BASE + "/chat", json={"message": message})
    response.raise_for_status()
    result = response.json()
    names = [call["name"] for call in result["tool_calls"]]
    assert names == [] if expected_tool is None else expected_tool in names
    if expected_text:
        assert expected_text in result["answer"]
    if expected_source:
        assert expected_source in result["sources"]
    actual = {(chunk["metadata"]["source"], chunk["metadata"]["page_number"])
              for call in result["tool_calls"] if call["name"] == "search_knowledge_base"
              for chunk in call["result"].get("results", [])}
    assert all((source["document"], source["page"]) in actual for source in result["sources"])
    if expected_tool != "search_knowledge_base":
        assert result["sources"] == []
    return {"message": message, "seconds": round(time.monotonic() - started, 2),
            "tools": names, "path": result["path"], "sources": result["sources"],
            "answer": result["answer"], "status": response.status_code}


def inventory(name):
    # 仅检查固定的公开知识库数量/来源；不读取 API Key 或原始业务文档。
    code = "import sqlite3; from pathlib import Path; p=next(Path('/app/data/vector-db').rglob('storage.sqlite')); c=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True); print(c.execute('SELECT COUNT(*) FROM points').fetchone()[0]); c.close()"
    return int(docker("exec", name, "python", "-c", code))


def main():
    from app.llm_client import read_configuration
    key, url, model = read_configuration()
    os.environ.update(DEEPSEEK_API_KEY=key, DEEPSEEK_BASE_URL=url, DEEPSEEK_MODEL=model)
    report = {"memory_limit_bytes": 512 * 1024 * 1024, "extra_swap_bytes": 0,
              "persistent_volumes": False, "cpu_limit": "not limited",
              "measurement": "cgroup v2 memory.current + kernel memory.peak; sampling interval >=0.3s",
              "requests": [], "status": "in_progress"}
    created = []
    monitors = []
    network_created = False
    try:
        docker("network", "create", NETWORK)
        network_created = True
        baseline = PREFIX + "-baseline"
        launch(baseline, False)
        created.append(baseline)
        report["baseline_start_seconds"] = wait_ready(baseline)
        report["baseline_memory"] = sample(baseline)
        docker("rm", "-f", baseline)
        created.remove(baseline)
        launch(BACKEND, True)
        created.append(BACKEND)
        monitor = Monitor(BACKEND)
        monitor.start()
        monitors.append(monitor)
        report["cold_start_seconds"] = wait_ready(BACKEND)
        report["initialization_memory"] = sample(BACKEND)
        monitor.phase = "idle"
        time.sleep(5)
        report["idle_memory"] = sample(BACKEND)
        docker("run", "-d", "--name", FRONTEND, "--label", "purpose=eka-memory-validation",
               "--network", NETWORK, "--memory", "512m", "--memory-swap", "512m",
               "-p", "127.0.0.1:18086:80", "knowledge-agent-memory:frontend")
        created.append(FRONTEND)
        with httpx.Client(timeout=180) as client:
            for attempt in range(30):
                page = client.get(WEB + "/")
                if page.status_code == 200 and 'id="root"' in page.text:
                    break
                time.sleep(1)
            report["frontend_http_status"] = page.status_code
            assert page.status_code == 200 and 'id="root"' in page.text
            assert client.get(WEB + "/api/health").json() == {"status": "ok"}
            assert client.post(BASE + "/documents", files={"file": ("demo.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 403
            report["frontend_and_health"] = "passed"
            cases = [
                ("你好，请简单介绍自己。", None, None, None),
                ("帮我计算 123 * 456", "calculator", "56088", None),
                ("Project Cedar 每位员工每月健康补贴是多少元？", "search_knowledge_base", "731", {"document": "web-demo-policy.pdf", "page": 1}),
                ("公司的报销需要哪些材料，多久提交？", "search_knowledge_base", None, {"document": "demo-company-policy.pdf", "page": 2}),
                ("公司的工作时间和报销流程分别是什么？", "search_knowledge_base", None, None),
                ("公司 CEO 的私人银行卡号是多少？只依据知识库回答。", "search_knowledge_base", None, None),
            ]
            monitor.phase = "requests"
            for case in cases:
                result = chat(client, *case)
                report["requests"].append(result)
                print("PASS request", len(report["requests"]), result["tools"], flush=True)
            report["runtime_memory"] = sample(BACKEND)
        monitor.phase = "inventory"
        report["chunk_count"] = inventory(BACKEND)
        assert report["chunk_count"] == 3
        monitor.phase = "recovery"
        # 常量路径仅存在于本脚本创建的测试容器；不接触主机数据库。
        docker("exec", BACKEND, "python", "-c", "import shutil; shutil.rmtree('/app/data/vector-db')")
        docker("restart", BACKEND)
        report["recovery_start_seconds"] = wait_ready(BACKEND)
        report["recovered_chunk_count"] = inventory(BACKEND)
        assert report["recovered_chunk_count"] == 3
        with httpx.Client(timeout=180) as client:
            report["recovery_request"] = chat(client, "Project Cedar 每月健康补贴是多少？", "search_knowledge_base", "731", {"document": "web-demo-policy.pdf", "page": 1})
        report["final_memory"] = sample(BACKEND)
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["failure_type"] = type(error).__name__
        print("VALIDATION FAILED:", type(error).__name__, flush=True)
        raise
    finally:
        report["samples"] = [reading for monitor in monitors for reading in monitor.finish()]
        report["unavailable_samples"] = sum(monitor.unavailable_samples for monitor in monitors)
        report["container_states"] = {name: state(name) for name in created}
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Report saved:", REPORT, flush=True)
        # 留下已创建的容器供诊断；不会自动删除失败证据或重试提高内存。
        if network_created:
            print("Test containers retained for inspection.", flush=True)


if __name__ == "__main__":
    main()
