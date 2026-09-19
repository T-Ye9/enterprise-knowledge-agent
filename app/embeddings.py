"""使用中文 ONNX 模型在 CPU 本地生成 dense embeddings。"""

from pathlib import Path

from fastembed import TextEmbedding
from .deployment import storage_path


MODEL_NAME = "BAAI/bge-small-zh-v1.5"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_CACHE = storage_path("EMBEDDING_CACHE_DIR", PROJECT_ROOT / ".cache" / "embeddings")


class Embedder:
    def __init__(self, model_name: str = MODEL_NAME, cache_dir: Path = MODEL_CACHE):
        self.model_name = model_name
        self.model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir), threads=2)
        self.dimension = next(iter(self.model.embed(["维度检查"]))).shape[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("待 embedding 的文本必须是非空字符串")
        return [vector.tolist() for vector in self.model.passage_embed(texts)]

    def embed_query(self, query: str) -> list[float]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query 不能为空")
        return next(iter(self.model.query_embed(query))).tolist()
