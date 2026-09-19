"""Agent 可调用的知识检索函数，只返回证据，不生成答案。"""

from .vector_store import DEFAULT_TOP_K


MAX_TOP_K = 10


def search_knowledge_base(query: str, top_k: int = DEFAULT_TOP_K) -> dict:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query 必须是非空字符串")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k 必须是 1 到 {MAX_TOP_K} 的整数")

    # 只有模型真正请求检索时，才初始化 embedding 模型和数据库。
    from .embeddings import Embedder
    from .knowledge_base import DATABASE_PATH, search_query
    from .vector_store import VectorStore

    embedder = Embedder()
    store = VectorStore(DATABASE_PATH, embedder.dimension, embedder.model_name)
    try:
        result = search_query(query, embedder, store, top_k)
    finally:
        store.close()
    for chunk in result["results"]:
        chunk["citation"] = chunk["metadata"]["chunk_id"]
    result["evidence_note"] = (
        "这些是检索片段，不是最终答案。score 不是事实可信度。"
        "只能依据正文回答；没有足够依据时明确说明，不能用常识补造企业规则。"
    )
    return result
