"""上传校验、入库复用、临时文件清理与浏览器 CORS 白名单。"""
import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.api import app
from app.document_upload import MAX_UPLOAD_BYTES, InvalidDocument, ingest_upload
from app.document_processing import DocumentError


def pdf_bytes(pages=1, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("test-password")
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


class UploadTests(unittest.TestCase):
    def test_invalid_file_and_path_rejected_before_embedding(self):
        with patch("app.embeddings.Embedder") as embedder:
            for name, content in [("../bad.pdf", b"%PDF-test"), ("D:\\bad.pdf", b"%PDF-test"),
                                  ("bad.txt", b"%PDF-test"), ("bad.pdf", b"not pdf"), ("bad.pdf", b""),
                                  ("bad[p1].pdf", b"%PDF-test"), ("bad.pdf", b"%PDF-test")]:
                with self.subTest(name=name), self.assertRaises(InvalidDocument):
                    ingest_upload(name, content)
        embedder.assert_not_called()

    def test_encrypted_and_page_limit_rejected(self):
        for content in [pdf_bytes(encrypted=True), pdf_bytes(101), pdf_bytes(0)]:
            with self.assertRaises(InvalidDocument):
                ingest_upload("test.pdf", content)

    def test_reuses_pipeline_unique_names_and_cleans_temp_files(self):
        paths = []
        def index(path, embedder, store, config):
            self.assertTrue(path.is_file())
            paths.append(path)
            return {"source": path.name, "pages": 1, "chunks_saved": 2}
        store = Mock()
        with patch("app.embeddings.Embedder"), patch("app.vector_store.VectorStore", return_value=store), patch("app.knowledge_base.index_pdf", side_effect=index) as ingestion:
            first = ingest_upload("policy.pdf", pdf_bytes())
            second = ingest_upload("policy.pdf", pdf_bytes())
        self.assertEqual(ingestion.call_count, 2)
        self.assertNotEqual(first["document"], second["document"])
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertEqual(store.close.call_count, 2)

    def test_cleanup_when_pipeline_fails(self):
        paths = []
        def fail(path, *args):
            paths.append(path)
            raise DocumentError("PDF 没有可用文本块")
        store = Mock()
        with patch("app.embeddings.Embedder"), patch("app.vector_store.VectorStore", return_value=store), patch("app.knowledge_base.index_pdf", side_effect=fail), self.assertRaises(InvalidDocument):
            ingest_upload("scan.pdf", pdf_bytes())
        self.assertFalse(paths[0].exists())
        store.close.assert_called_once()

    def test_http_upload_success_bad_missing_oversize_and_error(self):
        with TestClient(app) as http:
            with patch("app.api.ingest_upload", return_value={"document": "policy--test.pdf", "pages": 1, "chunks_saved": 2}) as ingest:
                result = http.post("/documents", files={"file": ("policy.pdf", pdf_bytes(), "application/pdf")})
                self.assertEqual(result.status_code, 201)
                self.assertEqual(result.json()["pages"], 1)
                ingest.assert_called_once()
                self.assertEqual(http.post("/documents").status_code, 422)
                oversized = http.post("/documents", files={"file": ("big.pdf", b"x" * (MAX_UPLOAD_BYTES + 1))})
                self.assertEqual(oversized.status_code, 413)
                self.assertEqual(ingest.call_count, 1)
            self.assertEqual(http.post("/documents", files={"file": ("fake.pdf", b"fake")}).status_code, 400)
            with patch("app.api.ingest_upload", side_effect=OSError("private path")):
                result = http.post("/documents", files={"file": ("test.pdf", pdf_bytes())})
                self.assertEqual(result.status_code, 503)
                self.assertNotIn("private path", result.text)

    def test_cors_allowed_and_unknown_origin(self):
        with TestClient(app) as http:
            headers = {"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
            allowed = http.options("/chat", headers=headers)
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.headers["access-control-allow-origin"], headers["Origin"])
            headers["Origin"] = "https://unknown.example"
            denied = http.options("/chat", headers=headers)
            self.assertEqual(denied.status_code, 400)
            self.assertNotIn("access-control-allow-origin", denied.headers)


if __name__ == "__main__":
    unittest.main()
