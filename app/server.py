"""生产启动：读取平台 PORT，始终单 worker，不启用 reload。"""
import os

import uvicorn

from .reliability import log_event


def server_port():
    try:
        port = int(os.getenv("PORT", "8000"))
    except ValueError:
        raise ValueError("PORT 必须为 1 至 65535 的整数") from None
    if not 1 <= port <= 65535:
        raise ValueError("PORT 必须为 1 至 65535 的整数")
    return port


def main():
    try:
        port = server_port()
    except ValueError as error:
        log_event("startup_configuration_invalid", error=error)
        raise SystemExit(1) from None
    uvicorn.run("app.api:app", host="0.0.0.0", port=port, workers=1, access_log=False)


if __name__ == "__main__":
    main()
