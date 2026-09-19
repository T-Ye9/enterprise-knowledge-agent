"""离线验证切分覆盖、重叠、页码和真实 PDF 集成。"""

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.chunking import ChunkConfig, chunk_pages
from app.document_processing import extract_pdf


def page(text, number=1):
    return {"text": text, "metadata": {
        "source": "test.pdf", "page_number": number,
        "page_count": 2, "title": "Test", "custom": "preserved",
    }}


class ChunkingTests(unittest.TestCase):
    def test_overlap_and_complete_coverage(self):
        text = "ABCDEFGHIJKLMNO"
        chunks = chunk_pages([page(text)], ChunkConfig(6, 2))
        self.assertEqual([chunk["text"] for chunk in chunks], [
            "ABCDEF", "EFGHIJ", "IJKLMN", "MNO",
        ])
        reconstructed = chunks[0]["text"]
        for previous, current in zip(chunks, chunks[1:]):
            self.assertEqual(previous["text"][-2:], current["text"][:2])
            reconstructed += current["text"][2:]
        self.assertEqual(reconstructed, text)
        for chunk in chunks:
            meta = chunk["metadata"]
            self.assertEqual(chunk["text"], text[meta["start_char"]:meta["end_char"]])
            self.assertLessEqual(len(chunk["text"]), 6)

    def test_page_isolation_and_metadata_copy(self):
        pages = [page("第一页中文正文", 1), page("第二页其他正文", 2)]
        original = copy.deepcopy(pages)
        chunks = chunk_pages(pages, ChunkConfig(5, 1))
        self.assertEqual(pages, original)
        ids = [chunk["metadata"]["chunk_id"] for chunk in chunks]
        self.assertEqual(len(ids), len(set(ids)))
        for chunk in chunks:
            metadata = chunk["metadata"]
            self.assertEqual(metadata["source"], "test.pdf")
            self.assertEqual(metadata["custom"], "preserved")
            original_page = pages[metadata["page_number"] - 1]
            self.assertIn(chunk["text"], original_page["text"])
        chunks[0]["metadata"]["title"] = "changed"
        self.assertEqual(pages, original)

    def test_empty_pages_do_not_renumber(self):
        chunks = chunk_pages([page(" \n", 1), page("有效文本", 2)])
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["metadata"]["page_number"], 2)
        self.assertEqual(chunk_pages([]), [])

    def test_exact_boundary_and_no_redundant_tail(self):
        for length in (1, 6, 10):
            with self.subTest(length=length):
                text = "x" * length
                chunks = chunk_pages([page(text)], ChunkConfig(6, 2))
                self.assertEqual(len(chunks), 1 if length <= 6 else 2)
                self.assertEqual(chunks[-1]["metadata"]["end_char"], length)

    def test_zero_overlap(self):
        text = "没有重叠也应该保留全部字符。"
        chunks = chunk_pages([page(text)], ChunkConfig(4, 0))
        self.assertEqual("".join(chunk["text"] for chunk in chunks), text)

    def test_invalid_config(self):
        for size, overlap in [(0, 0), (-1, 0), (5, -1), (5, 5), (5, 6), (True, 0), (5, 1.5)]:
            with self.subTest(size=size, overlap=overlap):
                with self.assertRaises(ValueError):
                    ChunkConfig(size, overlap)

    def test_real_pdf_and_stable_ids(self):
        pages = extract_pdf(ROOT / "samples" / "demo-company-policy.pdf")
        config = ChunkConfig(80, 20)
        chunks = chunk_pages(pages, config)
        self.assertGreater(len(chunks), len(pages))
        self.assertEqual(chunks, chunk_pages(pages, config))
        for original_page in pages:
            matching = [chunk for chunk in chunks if chunk["metadata"]["page_number"] == original_page["metadata"]["page_number"]]
            covered = set()
            for chunk in matching:
                meta = chunk["metadata"]
                covered.update(range(meta["start_char"], meta["end_char"]))
                self.assertEqual(meta["source"], "demo-company-policy.pdf")
                self.assertEqual(meta["page_count"], 2)
                self.assertEqual(chunk["text"], original_page["text"][meta["start_char"]:meta["end_char"]])
            self.assertEqual(covered, set(range(len(original_page["text"]))))


if __name__ == "__main__":
    unittest.main()
