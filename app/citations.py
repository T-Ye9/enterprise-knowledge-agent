"""引用标记只是模型的选择；来源字段必须由真实工具证据提供。"""

import json
import re


PDF_CITATION = re.compile(r"\[([^\[\]\n]*\.pdf[^\[\]\n]*)\]", re.IGNORECASE)


def resolve_citations(answer: str, messages: list[dict]) -> tuple[str, list[dict]]:
    """只接受真实知识检索的 chunk id，按 document/page 去重。

    messages 可包含本轮和历史工具结果，因此支持未再次检索的追问。
    不将用户文本或 assistant 的来源声明当作可信 metadata。
    """
    tool_names = {}
    evidence = {}
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls", []):
                tool_names[call["id"]] = call["function"]["name"]
        elif message.get("role") == "tool" and tool_names.get(message.get("tool_call_id")) == "search_knowledge_base":
            result = json.loads(message["content"])
            for chunk in result.get("results", []):
                metadata = chunk.get("metadata", {})
                document = metadata.get("source")
                page = metadata.get("page_number")
                chunk_id = metadata.get("chunk_id")
                if (isinstance(document, str) and document and isinstance(chunk_id, str)
                        and isinstance(page, int) and not isinstance(page, bool) and page > 0):
                    evidence[chunk_id] = {"document": document, "page": page}

    sources = []
    seen = set()

    def validate(match):
        source = evidence.get(match.group(1))
        if source is None:
            return ""  # 删除模型编造或仅出现在用户输入中的 PDF 来源标记。
        key = (source["document"], source["page"])
        if key not in seen:
            sources.append(source)
            seen.add(key)
        return match.group(0)

    return PDF_CITATION.sub(validate, answer), sources
