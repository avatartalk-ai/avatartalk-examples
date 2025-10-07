from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
import json
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from .config import settings
from .data import KnowledgeBase
from .openai_client import chat_complete, transcribe_audio_bytes
from .avatartalk_client import inference, AvatarTalkError


TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Ephemeral storage for pending streaming requests
pending_streams: Dict[str, Dict[str, Any]] = {}
STREAM_TTL = timedelta(minutes=10)

async def lifespan(app) -> None:

    async def janitor() -> None:
        while True:
            await asyncio.sleep(60)
            now = datetime.now(timezone.utc)
            expired = [sid for sid, info in list(pending_streams.items())
                       if info.get("expires_at") and info["expires_at"] < now]
            for sid in expired:
                pending_streams.pop(sid, None)

    # store task to cancel on shutdown
    app.state.knowledge_base = KnowledgeBase()
    app.state.knowledge_base.create_and_initialize_vector_store(settings.vector_store_name, settings.knowledge_base_directory_path)
    app.state._janitor_task = asyncio.create_task(janitor())

    yield

    app.state.knowledge_base.shut_down_vector_store()

    task = getattr(app.state, "_janitor_task", None)
    if task:
        task.cancel()

app = FastAPI(title="AvatarTalk - Knowledge-powered chat", lifespan=lifespan)

@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "model": settings.openai_model,
            "avatar": settings.avatar,
            "emotion": settings.emotion,
            "language": settings.language,
            "delayed": settings.delayed,
        },
    )


@app.post("/chat", response_class=JSONResponse)
async def chat(request: Request, payload: Dict[str, Any]) -> JSONResponse:
    """
    Accepts: {"user_text": str, "history": [{role, content}]?}
    Returns: {"assistant_text": str, "inference": {...}} (inference may include mp4_url/html_url)
    """
    user_text = (payload or {}).get("user_text")
    history: List[Dict[str, str]] = (payload or {}).get("history") or []
    if not user_text:
        return JSONResponse({"error": "user_text is required"}, status_code=400)

    # Build messages for OpenAI
    messages: List[Dict[str, str]] = []
    for msg in history:
        if msg.get("role") in {"system", "user", "assistant"} and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    assistant_text = chat_complete(messages, request.app.state.knowledge_base.vector_store_id)

    # Optional overrides from payload
    avatar = (payload or {}).get("avatar") or None
    emotion = (payload or {}).get("emotion") or None
    language = (payload or {}).get("language") or None

    # Generate video via AvatarTalk /inference for the assistant's text
    at_json: Dict[str, Any] = {}
    try:
        at_json = inference(
            assistant_text,
            avatar=avatar,
            emotion=emotion,
            language=language,
        )
    except Exception as e:
        # Return error but keep assistant_text
        at_json = {"status": "error", "message": str(e)}

    return JSONResponse({
        "assistant_text": assistant_text,
        "inference": at_json,
    })


@app.post("/voice", response_class=JSONResponse)
async def voice(
    audio: UploadFile = File(...),
    history: str | None = Form(None),
) -> JSONResponse:
    try:
        data = await audio.read()
        if not data:
            return JSONResponse({"error": "empty audio"}, status_code=400)
        # Parse history if provided
        msgs: List[Dict[str, str]] = []
        if history:
            try:
                parsed = json.loads(history)
                for msg in parsed or []:
                    if msg.get("role") in {"system", "user", "assistant"} and msg.get("content"):
                        msgs.append({"role": msg["role"], "content": msg["content"]})
            except Exception:
                pass

        # Transcribe with OpenAI
        user_text = transcribe_audio_bytes(data, filename=audio.filename or "audio.webm")
        if not user_text:
            return JSONResponse({"error": "transcription failed"}, status_code=500)

        msgs.append({"role": "user", "content": user_text})
        assistant_text = chat_complete(msgs)

        # Generate video via AvatarTalk
        at_json: Dict[str, Any] = {}
        try:
            at_json = inference(assistant_text)
        except Exception as e:
            at_json = {"status": "error", "message": str(e)}

        return JSONResponse({
            "user_text": user_text,
            "assistant_text": assistant_text,
            "inference": at_json,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/transcribe", response_class=JSONResponse)
async def transcribe(audio: UploadFile = File(...)) -> JSONResponse:
    data = await audio.read()
    if not data:
        return JSONResponse({"error": "empty audio"}, status_code=400)
    try:
        text = transcribe_audio_bytes(data, filename=audio.filename or "audio.webm")
        return JSONResponse({"user_text": text})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/chat_stream", response_class=JSONResponse)
async def chat_stream(payload: Dict[str, Any]) -> JSONResponse:
    """
    Initialize a streaming video generation for assistant's reply.
    Returns assistant_text and a stream_url to fetch the MP4 stream.
    """
    user_text = (payload or {}).get("user_text")
    history: List[Dict[str, str]] = (payload or {}).get("history") or []
    if not user_text:
        return JSONResponse({"error": "user_text is required"}, status_code=400)

    messages: List[Dict[str, str]] = []
    for msg in history:
        if msg.get("role") in {"system", "user", "assistant"} and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    assistant_text = chat_complete(messages)

    # Optional overrides from payload
    avatar = (payload or {}).get("avatar") or settings.avatar
    emotion = (payload or {}).get("emotion") or settings.emotion
    language = (payload or {}).get("language") or settings.language

    sid = str(uuid.uuid4())
    pending_streams[sid] = {
        "text": assistant_text,
        "avatar": avatar,
        "emotion": emotion,
        "language": language,
        "expires_at": datetime.now(timezone.utc) + STREAM_TTL,
    }
    return JSONResponse({
        "assistant_text": assistant_text,
        "stream_id": sid,
        "stream_url": f"/stream/{sid}.mp4",
    })


@app.get("/stream/{sid}.mp4")
def stream_video(sid: str):
    info = pending_streams.pop(sid, None)
    if not info:
        return JSONResponse({"error": "invalid or expired stream id"}, status_code=404)
    # If expired, reject
    if info.get("expires_at") and info["expires_at"] < datetime.now(timezone.utc):
        return JSONResponse({"error": "invalid or expired stream id"}, status_code=404)

    text = info["text"]
    payload = {
        "text": text,
        "avatar": info.get("avatar", settings.avatar),
        "emotion": info.get("emotion", settings.emotion),
        "language": info.get("language", settings.language),
    }
    base = settings.avatartalk_base_url.rstrip("/")
    url = f"{base}/inference?stream=true"
    headers = {
        "Authorization": f"Bearer {settings.avatartalk_api_key}",
        "Content-Type": "application/json",
    }

    def gen():
        with requests.post(url, json=payload, headers=headers, stream=True, timeout=None) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_content(chunk_size=16384):
                if chunk:
                    yield chunk

    return StreamingResponse(
        gen(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": "inline; filename=stream.mp4",
            "Cache-Control": "no-cache",
        },
    )
