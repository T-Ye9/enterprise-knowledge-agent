"""PDF 入库和 query 向量检索入口，不调用生成式 LLM。"""

import argparse
import json
from pathlib import Path

from .chunking import ChunkConfig, chunk_pages
from .document_processing import DocumentError, extract_pdf
from .embeddings import Embedder, MODEL_NAME, PROJECT_ROOT
from .vector_store import DEFAULT_TOP_K, VectorStore
from .deployment import storage_path


DATABASE_PATH = storage_path("KNOWLEDGE_DB_PATH", PROJECT_ROOT / "data" / "vector-db")


def index_pdf(path: Path, embedder: Embedder, store: VectorStore, config: ChunkConfig) -> dict:
    pages = extract_pdf(path)
    chunks = chunk_pages(pages, config)
    if not chunks:
        raise DocumentError("PDF 没有可用文本块，未写入数据库；扫描件可能需要 OCR")
    vectors = embedder.embed_documents([chunk["text"] for chunk in chunks])
    count = store.save_chunks(chunks, vectors)
    return {"source": path.name, "pages": len(pages), "chunks_saved": count,
            "embedding_model": embedder.model_name, "vector_dimension": embedder.dimension}


def search_query(query: str, embedder: Embedder, store: VectorStore, top_k: int = DEFAULT_TOP_K) -> dict:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("top_k 必须是正整数")
    vector = embedder.embed_query(query)
    return {"query": query, "embedding_model": embedder.model_name,
            "query_vector_dimension": len(vector), "top_k": top_k,
            "results": store.search(vector, top_k)}


def main():
    parser = argparse.ArgumentParser(description="本地 PDF 向量知识库：入库或检索")
    parser.add_argument("--db-path", type=Path, default=DATABASE_PATH)
    parser.add_argument("--model", default=MODEL_NAME)
    actions = parser.add_subparsers(dest="action", required=True)
    index = actions.add_parser("index")
    index.add_argument("pdf", type=Path)
    defaults = ChunkConfig()
    index.add_argument("--chunk-size", type=int, default=defaults.chunk_size)
    index.add_argument("--overlap", type=int, default=defaults.overlap)
    search = actions.add_parser("search")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    args = parser.parse_args()
    config = None
    try:
        if args.action == "index":
            config = ChunkConfig(args.chunk_size, args.overlap)
        elif args.top_k <= 0 or not args.query.strip():
            raise ValueError("query 不能为空，top_k 必须大于 0")
        embedder = Embedder(args.model)
        store = VectorStore(args.db_path, embedder.dimension, embedder.model_name)
        try:
            result = (index_pdf(args.pdf, embedder, store, config) if args.action == "index"
                      else search_query(args.query, embedder, store, args.top_k))
        finally:
            store.close()
    except (ValueError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
