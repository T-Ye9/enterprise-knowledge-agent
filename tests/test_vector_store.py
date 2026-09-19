"""真实本地 Qdrant 测试，不需下载 embedding 模型。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.vector_store import VectorStore


def chunk(identifier, text):
    return {"text": text, "metadata": {
        "source": "test.pdf", "page_number": 1, "chunk_id": identifier,
        "title": "Test", "custom": "preserved",
    }}


class VectorStoreTests(unittest.TestCase):
    def test_persistence_ranking_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            store = VectorStore(Path(folder), 2, "test-model")
            chunks = [chunk("test.pdf:p1:c1", "休假"), chunk("test.pdf:p1:c2", "报销")]
            try:
                store.save_chunks(chunks, [[1.0, 0.0], [0.0, 1.0]])
            finally:
                store.close()
            store = VectorStore(Path(folder), 2, "test-model")
            try:
                hits = store.search([1.0, 0.0], 1)
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["metadata"], chunks[0]["metadata"])
                self.assertEqual(hits[0]["text"], "休假")
                self.assertAlmostEqual(hits[0]["score"], 1.0, places=5)
                hits = store.search([1.0, 0.0], 10)
                self.assertEqual(len(hits), 2)
                self.assertGreater(hits[0]["score"], hits[1]["score"])
            finally:
                store.close()

    def test_reindex_removes_old_chunks(self):
        with tempfile.TemporaryDirectory() as folder:
            store = VectorStore(Path(folder), 2, "test-model")
            try:
                store.save_chunks([chunk("c1", "old"), chunk("c2", "old tail")], [[1., 0.], [0., 1.]])
                store.save_chunks([chunk("c1", "new")], [[1., 0.]])
                hits = store.search([1., 0.], 10)
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["text"], "new")
            finally:
                store.close()

    def test_invalid_vectors_and_top_k(self):
        with tempfile.TemporaryDirectory() as folder:
            store = VectorStore(Path(folder), 2, "test-model")
            try:
                for vector in ([1.], [float("nan"), 0.], [0., 0.]):
                    with self.subTest(vector=vector), self.assertRaises(ValueError):
                        store.search(vector)
                for k in (0, -1, True, 1.5):
                    with self.subTest(k=k), self.assertRaises(ValueError):
                        store.search([1., 0.], k)
                with self.assertRaises(ValueError):
                    store.save_chunks([chunk("c1", "x")], [])
            finally:
                store.close()

    def test_model_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = VectorStore(Path(folder), 2, "model-one")
            store.save_chunks([chunk("c1", "one")], [[1., 0.]])
            store.close()
            store = VectorStore(Path(folder), 2, "model-two")
            try:
                self.assertEqual(store.search([1., 0.]), [])
            finally:
                store.close()

    def test_dimension_mismatch_on_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            store = VectorStore(Path(folder), 2, "model-one")
            store.close()
            with self.assertRaises(ValueError):
                VectorStore(Path(folder), 3, "model-one")


if __name__ == "__main__":
    unittest.main()
