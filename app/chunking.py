"""把阶段 3 的逐页文本切为保留来源信息的字符窗口。"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from .document_processing import extract_pdf


@dataclass(frozen=True)
class ChunkConfig:
    """按 Python 字符数计量，不是模型 token 数。"""

    chunk_size: int = 500
    overlap: int = 50

    def __post_init__(self):
        for value in (self.chunk_size, self.overlap):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("chunk_size 和 overlap 必须是整数")
        if self.chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0")
        if not 0 <= self.overlap < self.chunk_size:
            raise ValueError("overlap 必须满足 0 <= overlap < chunk_size")


DEFAULT_CONFIG = ChunkConfig()


def chunk_pages(pages: list[dict], config: ChunkConfig = DEFAULT_CONFIG) -> list[dict]:
    """每页独立切分；不改动原文及原 metadata，不生成空白 chunk。"""
    chunks = []
    step = config.chunk_size - config.overlap
    for page in pages:
        text = page["text"]
        metadata = page["metadata"]
        if not isinstance(text, str):
            raise ValueError("每页 text 必须是字符串")
        if not text.strip():
            continue
        source = metadata["source"]
        page_number = metadata["page_number"]
        chunk_number = 0
        for start in range(0, len(text), step):
            end = min(start + config.chunk_size, len(text))
            chunk_text = text[start:end]
            if chunk_text.strip():
                chunk_number += 1
                chunks.append({
                    "text": chunk_text,
                    "metadata": {
                        **metadata,
                        "chunk_id": f"{source}:p{page_number}:c{chunk_number}",
                        "chunk_number": chunk_number,
                        "start_char": start,
                        "end_char": end,
                    },
                })
            # 已到页尾就停止，不再输出完全包含于上一块的重叠尾片。
            if end == len(text):
                break
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="PDF → Pages → Text → Chunks")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CONFIG.chunk_size)
    parser.add_argument("--overlap", type=int, default=DEFAULT_CONFIG.overlap)
    arguments = parser.parse_args()
    try:
        config = ChunkConfig(arguments.chunk_size, arguments.overlap)
        chunks = chunk_pages(extract_pdf(arguments.pdf), config)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(json.dumps(chunks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
