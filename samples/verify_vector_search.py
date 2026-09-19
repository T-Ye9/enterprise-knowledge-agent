"""真实中文模型端到端验收，只输出公开虚构样本结果。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.chunking import ChunkConfig
from app.embeddings import Embedder
from app.knowledge_base import DATABASE_PATH, index_pdf, search_query
from app.vector_store import VectorStore


def main():
    embedder = Embedder()
    store = VectorStore(DATABASE_PATH, embedder.dimension, embedder.model_name)
    try:
        indexed = index_pdf(ROOT / "samples" / "demo-company-policy.pdf", embedder, store, ChunkConfig(80, 20))
    finally:
        store.close()
    print("Index:", json.dumps(indexed, ensure_ascii=False))
    # 关闭后重新打开，验证结果来自磁盘数据库。
    store = VectorStore(DATABASE_PATH, embedder.dimension, embedder.model_name)
    try:
        result = search_query("出差回来后，多久之内要提交报销？", embedder, store, top_k=2)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        assert len(result["results"]) == 2
        top = result["results"][0]
        assert top["metadata"]["page_number"] == 2
        assert top["metadata"]["source"] == "demo-company-policy.pdf"
        assert top["metadata"]["chunk_id"] == "demo-company-policy.pdf:p2:c1"
        assert "十个工作日" in top["text"]
        assert result["results"][0]["score"] >= result["results"][1]["score"]
        (ROOT / "samples" / "vector_search_example.json").write_text(
            json.dumps({"index": indexed, "search": result}, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print("PASS: real Chinese embedding → persistent vector search → Top-K sources")
    finally:
        store.close()


if __name__ == "__main__":
    main()
