from __future__ import annotations

import requests
from typing import Any, Dict

from .config import settings


class AvatarTalkError(RuntimeError):
    pass


def inference(
    text: str,
    *,
    avatar: str | None = None,
    emotion: str | None = None,
    language: str | None = None,
    delayed: bool | None = None,
) -> Dict[str, Any]:
    """
    Call POST {base_url}/inference and return parsed JSON.
    """
    if not settings.avatartalk_api_key:
        raise RuntimeError("AVATARTALK_API_KEY is not set")

    base = settings.avatartalk_base_url.rstrip("/")
    url = f"{base}/inference"
    payload = {
        "text": text,
        "avatar": avatar or settings.avatar,
        "emotion": emotion or settings.emotion,
        "language": language or settings.language,
    }
    use_delayed = delayed if delayed is not None else settings.delayed
    if use_delayed:
        payload["delayed"] = True

    headers = {
        "Authorization": f"Bearer {settings.avatartalk_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    if resp.status_code >= 400:
        raise AvatarTalkError(
            f"AvatarTalk inference failed: {resp.status_code} {resp.text}"
        )
    return resp.json()
