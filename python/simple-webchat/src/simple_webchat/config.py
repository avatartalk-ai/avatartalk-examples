from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv


# Load .env if present (supports .env in CWD or parents)
load_dotenv()  # noqa: F401


def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # OpenAI
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_stt_model: str = os.getenv("OPENAI_STT_MODEL", "whisper-1")

    # AvatarTalk
    avatartalk_api_key: str | None = os.getenv("AVATARTALK_API_KEY") or os.getenv("AT_API_KEY")
    avatartalk_base_url: str = os.getenv("AVATARTALK_API_BASE", "https://api.avatartalk.ai")

    # Defaults for inference
    avatar: str = os.getenv("AVATARTALK_AVATAR", "european_woman")
    emotion: str = os.getenv("AVATARTALK_EMOTION", "neutral")
    language: str = os.getenv("AVATARTALK_LANGUAGE", "en")
    delayed: bool = _get_bool("AVATARTALK_DELAYED", False)

    # Server config
    host: str = os.getenv("APP_HOST", "127.0.0.1")
    port: int = int(os.getenv("APP_PORT", "8000"))
    debug: bool = _get_bool("APP_DEBUG", True)


settings = Settings()
