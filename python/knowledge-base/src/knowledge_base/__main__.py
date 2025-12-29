from __future__ import annotations

import uvicorn

from .config import settings


def main() -> None:
    uvicorn.run(
        "knowledge_base.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=1
    )


if __name__ == "__main__":
    main()

