from __future__ import annotations

from typing import List, Dict, Any
import io
from tempfile import NamedTemporaryFile
from openai import OpenAI

from .config import settings


def build_openai_client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=settings.openai_api_key)


def chat_complete(
    messages: List[Dict[str, Any]],
    model: str | None = None,
) -> str:
    client = build_openai_client()
    mdl = model or settings.openai_model
    # Use Chat Completions for simplicity
    resp = client.chat.completions.create(
        model=mdl,
        messages=messages,
        temperature=0.7,
    )
    choice = resp.choices[0]
    return choice.message.content or ""


def transcribe_audio_bytes(data: bytes, filename: str = "audio.webm", model: str | None = None) -> str:
    client = build_openai_client()
    mdl = model or settings.openai_stt_model
    # Use a temporary file to ensure the SDK includes filename and content-type correctly
    with NamedTemporaryFile(suffix=filename[filename.rfind("."): ] if "." in filename else ".webm") as tmp:
        tmp.write(data)
        tmp.flush()
        with open(tmp.name, "rb") as f:
            tr = client.audio.transcriptions.create(
                model=mdl,
                file=f,
            )
    # The response has .text for Whisper-like models
    # For newer models, the SDK still returns `.text` consistently
    return getattr(tr, "text", "") or ""
