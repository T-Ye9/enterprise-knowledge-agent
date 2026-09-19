"""Qdrant 本地数据库，持久化向量、正文和全部来源 metadata。"""

import hashlib
import math
import uuid
from pathlib import Path

from qdrant_client import QdrantClient, models


DEFAULT_TOP_K = 3


class VectorStore:
    def __init__(self, path: Path, dimension: int, model_name: str):
        self.dimension = dimension
        self.model_name = model_name
        # 不同模型不共用向量空间，即使向量维度相同。
        self.collection = "chunks_" + hashlib.sha256(model_name.encode()).hexdigest()[:12]
        self.client = QdrantClient(path=str(path))
        try:
            if not self.client.collection_exists(self.collection):
                self.client.create_collection(
                    self.collection,
                    vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
                )
            else:
                parameters = self.client.get_collection(self.collection).config.params.vectors
                if parameters.size != dimension or parameters.distance != models.Distance.COSINE:
                    raise ValueError("数据库向量维度或距离配置与当前模型不一致")
        except Exception:
            self.client.close()
            raise

    def close(self):
        self.client.close()

    def _validate_vector(self, vector):
        if len(vector) != self.dimension or not all(math.isfinite(value) for value in vector):
            raise ValueError("向量维度不匹配或包含非有限数字")
        if not any(value != 0 for value in vector):
            raise ValueError("不能使用零向量进行 cosine 检索")

    def save_chunks(self, chunks: list[dict], vectors: list[list[float]]) -> int:
        if len(chunks) != len(vectors) or not chunks:
            raise ValueError("chunks 和 vectors 必须非空且数量一致")
        points = []
        for chunk, vector in zip(chunks, vectors):
            self._validate_vector(vector)
            metadata = chunk["metadata"]
            identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, metadata["chunk_id"]))
            points.append(models.PointStruct(
                id=identifier, vector=vector,
                payload={"text": chunk["text"], "metadata": metadata, "embedding_model": self.model_name},
            ))
        # 当前按文件名区分文档；重新索引时移除旧块，避免修改 size 后残留旧块。
        for source in sorted({chunk["metadata"]["source"] for chunk in chunks}):
            self.client.delete(self.collection, points_selector=models.FilterSelector(
                filter=models.Filter(must=[models.FieldCondition(
                    key="metadata.source", match=models.MatchValue(value=source),
                )]),
            ), wait=True)
        self.client.upsert(self.collection, points=points, wait=True)
        return len(points)

    def search(self, query_vector: list[float], top_k: int = DEFAULT_TOP_K) -> list[dict]:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k 必须是正整数")
        self._validate_vector(query_vector)
        hits = self.client.query_points(
            collection_name=self.collection, query=query_vector,
            limit=top_k, with_payload=True,
        ).points
        return [{
            "score": hit.score,
            "text": hit.payload["text"],
            "metadata": hit.payload["metadata"],
        } for hit in hits]
