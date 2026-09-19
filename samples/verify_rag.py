"""已有公开样本库的真实 RAG 验收；消耗 DeepSeek API 额度，不重新入库。"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.embeddings import Embedder
from app.knowledge_base import DATABASE_PATH
from app.llm_client import create_client
from app.rag import run_rag
from app.vector_store import VectorStore


def main():
    client, model = create_client()
    results = []
    try:
        embedder = Embedder()
        store = VectorStore(DATABASE_PATH, embedder.dimension, embedder.model_name)
        try:
            for question in [
                "出差回来后，多久之内要提交报销？",
                "公司员工每年的年终奖金是多少元？",
                "休假需要提前多久申请，出差报销需要在返回后多久提交？",
            ]:
                result = run_rag(question, embedder, store, client, model, top_k=3)
                results.append(result)
                print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        finally:
            store.close()
    finally:
        client.close()
    # 先保存实际结果，再断言；失败不会伪装成成功。
    (ROOT / "samples" / "rag_examples.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    assert re.search(r"(?:十|10)个工作日", results[0]["answer"])
    assert re.search(r"\[\d+\]", results[0]["answer"])
    assert "没有足够依据" in results[1]["answer"]
    assert re.search(r"(?:三|3)个工作日", results[2]["answer"])
    assert re.search(r"(?:十|10)个工作日", results[2]["answer"])
    cited = {int(number) for number in re.findall(r"\[(\d+)\]", results[2]["answer"])}
    assert len(cited) >= 2
    assert {results[2]["sources"][number - 1]["metadata"]["page_number"] for number in cited} == {1, 2}
    print("PASS: known question, unsupported question, and multi-chunk RAG", flush=True)


if __name__ == "__main__":
    main()
