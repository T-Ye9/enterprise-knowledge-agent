"""独立的 PDF 文本解析模块，不依赖 LLM 或 API Key。"""

import argparse
import json
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class DocumentError(ValueError):
    """文档本身无效或没有可用于入库的文本。"""


def extract_pdf(path: str | Path) -> list[dict]:
    """逐页返回文本和来源元数据，保留无文本页面的原始页码。"""
    source = Path(path)
    if source.suffix.lower() != ".pdf":
        raise ValueError("请输入 .pdf 文件")
    if not source.is_file():
        raise FileNotFoundError(f"PDF 文件不存在：{source}")

    try:
        with source.open("rb") as stream:
            reader = PdfReader(stream)
            if reader.is_encrypted:
                raise DocumentError("暂不支持加密 PDF，请提供未加密的授权副本")
            title = str((reader.metadata or {}).get("/Title") or "")
            page_count = len(reader.pages)
            pages = []
            for page_number, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                pages.append({
                    "text": text,
                    "metadata": {
                        "source": source.name,
                        "page_number": page_number,
                        "page_count": page_count,
                        "title": title,
                        "text_status": "extracted" if text else "no_text",
                    },
                })
            return pages
    except PdfReadError as error:
        raise DocumentError("无法解析 PDF，文件可能损坏或不是有效 PDF") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="按页提取 PDF 文本及元数据")
    parser.add_argument("pdf", type=Path, help="本地 PDF 路径")
    arguments = parser.parse_args()
    try:
        pages = extract_pdf(arguments.pdf)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(json.dumps(pages, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
