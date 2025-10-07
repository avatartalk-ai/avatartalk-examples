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

def get_vector_store_id() -> str:
    with open(".vector_store_id", "r") as f:
        return f.read().strip()

def chat_complete(
    messages: List[Dict[str, Any]],
    vector_store_id: str,
    model: str | None = None,
) -> str:
    client = build_openai_client()
    vector_store_id = get_vector_store_id()

    mdl = model or settings.openai_model
    resp = client.responses.create(
        model=mdl,
        input=messages,
        temperature=0.7,
        tools=[{
            "type": "file_search",
            "vector_store_ids": [vector_store_id]
        }]
    )

    return resp.output[1].content[0].text


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
