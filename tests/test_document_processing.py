"""通过真实 PDF 验证文本、页码、元数据及错误情况。"""

import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from document_processing import extract_pdf


class DocumentProcessingTests(unittest.TestCase):
    def test_sample_text_and_metadata(self):
        pages = extract_pdf(ROOT / "samples" / "demo-company-policy.pdf")
        self.assertEqual(len(pages), 2)
        self.assertIn("休假申请", pages[0]["text"])
        self.assertIn("差旅报销", pages[1]["text"])
        self.assertNotIn("报销期限", pages[0]["text"])
        for number, page in enumerate(pages, start=1):
            self.assertEqual(page["metadata"], {
                "source": "demo-company-policy.pdf", "page_number": number,
                "page_count": 2, "title": "Fictional Company Policy",
                "text_status": "extracted",
            })

    def test_empty_page_preserves_page_number(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "empty.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            writer.write(path)
            pages = extract_pdf(path)
            self.assertEqual(pages[0]["text"], "")
            self.assertEqual(pages[0]["metadata"]["page_number"], 1)
            self.assertEqual(pages[0]["metadata"]["text_status"], "no_text")

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                extract_pdf(Path(folder) / "missing.pdf")

    def test_wrong_extension(self):
        with self.assertRaises(ValueError):
            extract_pdf("policy.txt")

    def test_invalid_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.pdf"
            path.write_bytes(b"%PDF-1.4\ninvalid content\n")
            with self.assertRaisesRegex(ValueError, "无法解析"):
                extract_pdf(path)

    def test_encrypted_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "encrypted.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            writer.encrypt("test-password")
            writer.write(path)
            with self.assertRaisesRegex(ValueError, "加密"):
                extract_pdf(path)


if __name__ == "__main__":
    unittest.main()
