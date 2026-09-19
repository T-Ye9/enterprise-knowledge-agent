"""有边界的本地 PDF 上传，复用 index_pdf，不长期保存原文件。"""
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from .document_processing import DocumentError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 100


class InvalidDocument(ValueError):
    pass


def ingest_upload(filename: str, content: bytes) -> dict:
    if not filename or len(filename) > 120 or re.search(r'[\\/<>:"|?*\[\]\x00-\x1f]', filename):
        raise InvalidDocument("文件名无效，请使用不含路径和特殊符号的文件名")
    if Path(filename).suffix.lower() != ".pdf":
        raise InvalidDocument("只支持 PDF 文件")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise InvalidDocument("PDF 不能为空，且不能超过 10 MB")
    if not content.startswith(b"%PDF-"):
        raise InvalidDocument("文件不是有效 PDF")
    # 唯一来源名避免同名上传触发现有 store 的重新索引覆盖逻辑。
    document = f"{Path(filename).stem}--{uuid4().hex[:12]}.pdf"
    with TemporaryDirectory(prefix="knowledge-upload-") as directory:
        path = Path(directory) / document
        path.write_bytes(content)
        try:
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise InvalidDocument("暂不支持加密 PDF")
            if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
                raise InvalidDocument("PDF 必须包含 1 至 100 页")
        except PdfReadError as error:
            raise InvalidDocument("PDF 已损坏或无法解析") from error
        # 延迟初始化，仅有效上传才加载模型、打开向量库。
        from .chunking import ChunkConfig
        from .embeddings import Embedder
        from .knowledge_base import DATABASE_PATH, index_pdf
        from .vector_store import VectorStore
        embedder = Embedder()
        store = VectorStore(DATABASE_PATH, embedder.dimension, embedder.model_name)
        try:
            try:
                result = index_pdf(path, embedder, store, ChunkConfig())
            except DocumentError as error:
                raise InvalidDocument("PDF 无法提取有效文本，可能损坏、为空或需要 OCR") from error
        finally:
            store.close()
    return {"document": result["source"], "pages": result["pages"], "chunks_saved": result["chunks_saved"]}
