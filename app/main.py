"""终端运行原生 Tool Calling，展示模型请求和 Python 执行结果。"""

import sys
from pathlib import Path
from openai import OpenAIError

# 保留 python app/main.py，同时支持 python -m app.main。
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm_client import create_client
from app.tool_runtime import SYSTEM_PROMPT, execute_tool




def run_conversation(client, model: str, user_input: str) -> dict:
    """保留原函数入口，内部由 LangGraph Agent 编排。"""
    from app.agent import run_agent
    return run_agent(client, model, user_input)

def main() -> None:
    try:
        client, model = create_client()
        user_input = input("请输入问题：").strip()
        if not user_input:
            raise ValueError("请输入非空问题。")
        try:
            trace = run_conversation(client, model, user_input)
            # 明确的终端输出，不作为服务日志记录问题/答案或检索正文。
            print(trace["final_answer"])
        finally:
            client.close()
    except (ValueError, OpenAIError) as error:
        if isinstance(error, OpenAIError):
            # 不打印 API 异常正文，避免回显可能包含的敏感配置。
            print(f"API Error: {type(error).__name__}; HTTP Status: {getattr(error, 'status_code', None)}")
            print("请检查网络、API 地址、模型、密钥及账户额度。")
        else:
            print(f"Error: {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
