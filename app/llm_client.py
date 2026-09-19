"""普通聊天和 RAG 共用的 LLM 客户端配置。"""

import os
from urllib.parse import urlparse
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_configuration():
    """定位项目 .env，不依赖终端当前目录。"""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key or api_key in {"your_api_key_here", "你的真实密钥"}:
        raise ValueError("请在项目 .env 中填写 DEEPSEEK_API_KEY，然后重新运行。")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("DEEPSEEK_BASE_URL 必须是无凭据、查询参数的 HTTP(S) 地址")
    if not model:
        raise ValueError("DEEPSEEK_MODEL 不能为空")
    return api_key, base_url, model


def create_client():
    api_key, base_url, model = read_configuration()
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=60.0,
        max_retries=0,
    )
    return client, model
