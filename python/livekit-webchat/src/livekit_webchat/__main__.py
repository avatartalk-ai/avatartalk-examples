from __future__ import annotations

import uvicorn

from .config import settings


def main() -> None:
    uvicorn.run(
        "livekit_webchat.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
