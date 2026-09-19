"""可选的固定公开 Demo 入库；复用现有 ingestion，不加载私有文件。"""
import os

from .deployment import PROJECT_ROOT
from .reliability import log_event


def bootstrap_demo():
    enabled = os.getenv("BOOTSTRAP_DEMO_KNOWLEDGE_BASE", "false").strip().lower()
    if enabled not in {"true", "false"}:
        raise ValueError("BOOTSTRAP_DEMO_KNOWLEDGE_BASE 必须为 true 或 false")
    if enabled == "false":
        return
    from .chunking import ChunkConfig
    from .embeddings import Embedder
    from .knowledge_base import DATABASE_PATH, index_pdf
    from .vector_store import VectorStore

    documents = [PROJECT_ROOT / "samples" / name for name in
                 ("demo-company-policy.pdf", "web-demo-policy.pdf")]
    if any(not document.is_file() for document in documents):
        raise ValueError("内置公开 Demo PDF 缺失，无法初始化知识库")
    log_event("demo_initialization_started")
    embedder = Embedder()
    store = VectorStore(DATABASE_PATH, embedder.dimension, embedder.model_name)
    try:
        # 每次启动重建两个公开来源，已有 save_chunks 会替换同来源，避免重复。
        # 即使上一轮在第二个 PDF 失败，下次启动也不会把半成品当作完整库。
        for document in documents:
            index_pdf(document, embedder, store, ChunkConfig())
    finally:
        store.close()
    log_event("demo_initialization_finished")
