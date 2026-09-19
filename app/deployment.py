"""与托管平台无关的部署配置及启动检查。"""
import os
from pathlib import Path
from tempfile import TemporaryFile
from urllib.parse import urlparse

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def production():
    mode = os.getenv("APP_ENV", "development").strip()
    if mode not in {"development", "production"}:
        raise ValueError("APP_ENV 必须为 development 或 production")
    return mode == "production"


def uploads_enabled():
    value = os.getenv("ALLOW_DOCUMENT_UPLOAD", "false" if production() else "true").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError("ALLOW_DOCUMENT_UPLOAD 必须为 true 或 false")
    return value == "true"


def storage_path(name, default):
    value = os.getenv(name)
    if value is None:
        return Path(default)
    if not value.strip():
        raise ValueError(f"{name} 不能为空")
    return Path(value).expanduser().resolve()


def cors_origins():
    value = os.getenv("CORS_ORIGINS")
    if value is None:
        if production():
            raise ValueError("production 必须显式配置 CORS_ORIGINS；同源代理可设为空")
        value = "http://127.0.0.1:5173,http://localhost:5173"
    origins = [item.strip() for item in value.split(",") if item.strip()]
    if production():
        for origin in origins:
            try:
                parsed = urlparse(origin)
                parsed.port
            except ValueError:
                raise ValueError("production CORS_ORIGINS 包含无效 origin") from None
            if "*" in origin or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                raise ValueError("production CORS_ORIGINS 必须为 HTTPS origin，不允许通配符或路径")
    return origins


def validate_deployment():
    uploads_enabled()
    cors_origins()
    if not production():
        return
    from .llm_client import read_configuration
    _, base_url, _ = read_configuration()  # 只验证配置，不调用供应商 API。
    if urlparse(base_url).scheme != "https":
        raise ValueError("production LLM API 必须使用 HTTPS")
    for name in ("KNOWLEDGE_DB_PATH", "EMBEDDING_CACHE_DIR"):
        if not os.getenv(name, "").strip() or not Path(os.environ[name]).is_absolute():
            raise ValueError(f"production 必须显式配置绝对路径 {name}")
        path = storage_path(name, PROJECT_ROOT)
        try:
            path.mkdir(parents=True, exist_ok=True)
            with TemporaryFile(dir=path):
                pass
        except OSError:
            raise ValueError(f"{name} 不可写，请检查持久卷挂载和运行用户权限") from None
