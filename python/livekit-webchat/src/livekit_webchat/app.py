from __future__ import annotations

import traceback
from typing import Any, Dict, List
import json
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from urllib.parse import quote
from websockets.sync.client import connect
from .config import settings
from .openai_client import chat_complete, transcribe_audio_bytes


app = FastAPI(title="AvatarTalk · LiveKit WebChat")

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# In-memory session store (ephemeral)
class SessionInfo(Dict[str, Any]):
    pass


sessions: Dict[str, SessionInfo] = {}
SESSION_TTL = timedelta(hours=6)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mint_livekit_token(
    *,
    identity: str,
    name: str,
    room: str,
    can_publish: bool,
    can_subscribe: bool,
) -> str:
    from livekit import api as lk_api

    if not settings.livekit_api_key or not settings.livekit_api_secret:
        raise RuntimeError("LIVEKIT_API_KEY/SECRET not set")
    grants_kwargs = {"room_join": True, "room": room}
    token = (
        lk_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_grants(lk_api.VideoGrants(**grants_kwargs))
    )
    return token.to_jwt()


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
            "livekit_url": settings.livekit_url or "",
        },
    )


@app.post("/session", response_class=JSONResponse)
async def create_session(payload: Dict[str, Any] | None = None) -> JSONResponse:
    if not settings.livekit_url:
        return JSONResponse({"error": "LIVEKIT_URL is not set"}, status_code=500)
    # One room per session
    session_id = str(uuid.uuid4())
    room_name = f"lk-{session_id[:8]}"
    user_identity = f"user-{session_id[:8]}"
    avatar_identity = f"avatar-{session_id[:8]}"
    # Optionally create the room up-front for clarity
    try:
        from livekit import api as lk_api

        lkapi = lk_api.LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        await lkapi.room.create_room(lk_api.CreateRoomRequest(name=room_name))
        await lkapi.aclose()
    except Exception:
        # If room already exists or server auto-creates on join, ignore
        pass

    user_token = _mint_livekit_token(
        identity=user_identity,
        name=user_identity,
        room=room_name,
        can_publish=False,
        can_subscribe=True,
    )
    avatar_token = _mint_livekit_token(
        identity=avatar_identity,
        name=avatar_identity,
        room=room_name,
        can_publish=True,
        can_subscribe=False,
    )

    sessions[session_id] = SessionInfo(
        {
            "room": room_name,
            "avatar_token": avatar_token,
            "created_at": _now(),
            "expires_at": _now() + SESSION_TTL,
        }
    )
    return JSONResponse(
        {
            "session_id": session_id,
            "room_name": room_name,
            "livekit_url": settings.livekit_url,
            "token": user_token,
        }
    )


def _cleanup_sessions() -> None:
    now = _now()
    expired = [
        sid
        for sid, s in sessions.items()
        if s.get("expires_at") and s["expires_at"] < now
    ]
    for sid in expired:
        sessions.pop(sid, None)


def _send_text_to_avatar_via_ws(
    *,
    meeting_token: str,
    text: str,
    avatar: str,
    emotion: str,
    language: str,
    increase_resolution: bool,
) -> None:
    base = settings.avatartalk_base_url.rstrip("/")
    # Pass all required params in query string; authenticate via Authorization header
    qs = (
        f"output_type=livekit&input_type=text&avatar={quote(avatar)}"
        f"&emotion={quote(emotion)}&language={quote(language)}"
        f"&meeting_token={quote(meeting_token)}"
        f"&increase_resolution={'true' if increase_resolution else 'false'}"
        f"&livekit_url={settings.livekit_url}"
    )
    url = f"{base}/ws/infer?{qs}"
    headers = {"Authorization": f"Bearer {settings.avatartalk_api_key}"}
    with connect(url, additional_headers=headers, timeout=30) as ws:
        ws.send(text.encode("utf-8"))
        ws.send(b"!!!Close!!!")


@app.post("/chat", response_class=JSONResponse)
async def chat(payload: Dict[str, Any]) -> JSONResponse:
    """
    Accepts: {session_id, user_text, history?, avatar?, emotion?, language?, increase_resolution?}
    Returns: {assistant_text}
    """
    _cleanup_sessions()
    user_text = (payload or {}).get("user_text")
    session_id = (payload or {}).get("session_id")
    history: List[Dict[str, str]] = (payload or {}).get("history") or []
    if not user_text:
        return JSONResponse({"error": "user_text is required"}, status_code=400)
    if not session_id or session_id not in sessions:
        return JSONResponse({"error": "invalid session_id"}, status_code=400)

    messages: List[Dict[str, str]] = []
    for msg in history:
        if msg.get("role") in {"system", "user", "assistant"} and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    assistant_text = chat_complete(messages)

    avatar = (payload or {}).get("avatar") or settings.avatar
    emotion = (payload or {}).get("emotion") or settings.emotion
    language = (payload or {}).get("language") or settings.language
    increase_resolution = bool((payload or {}).get("increase_resolution"))

    if not settings.avatartalk_api_key:
        return JSONResponse({"error": "AVATARTALK_API_KEY is not set"}, status_code=500)

    meeting_token = sessions[session_id]["avatar_token"]
    try:
        _send_text_to_avatar_via_ws(
            meeting_token=meeting_token,
            text=assistant_text,
            avatar=avatar,
            emotion=emotion,
            language=language,
            increase_resolution=increase_resolution,
        )
    except Exception as e:
        print(traceback.format_exc())
        return JSONResponse(
            {"assistant_text": assistant_text, "warning": f"avatar stream error: {e}"},
            status_code=500,
        )

    return JSONResponse({"assistant_text": assistant_text})


@app.post("/voice", response_class=JSONResponse)
async def voice(
    audio: UploadFile = File(...),
    history: str | None = Form(None),
    session_id: str | None = Form(None),
    avatar: str | None = Form(None),
    emotion: str | None = Form(None),
    language: str | None = Form(None),
    increase_resolution: str | None = Form(None),
) -> JSONResponse:
    _cleanup_sessions()
    if not session_id or session_id not in sessions:
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    try:
        data = await audio.read()
        if not data:
            return JSONResponse({"error": "empty audio"}, status_code=400)
        msgs: List[Dict[str, str]] = []
        if history:
            try:
                parsed = json.loads(history)
                for msg in parsed or []:
                    if msg.get("role") in {"system", "user", "assistant"} and msg.get(
                        "content"
                    ):
                        msgs.append({"role": msg["role"], "content": msg["content"]})
            except Exception:
                pass
        user_text = transcribe_audio_bytes(
            data, filename=audio.filename or "audio.webm"
        )
        if not user_text:
            return JSONResponse({"error": "transcription failed"}, status_code=500)
        msgs.append({"role": "user", "content": user_text})
        assistant_text = chat_complete(msgs)

        avatar_v = avatar or settings.avatar
        emotion_v = emotion or settings.emotion
        language_v = language or settings.language
        inc_res = (increase_resolution or "").lower() in {"1", "true", "yes", "on"}

        if not settings.avatartalk_api_key:
            return JSONResponse(
                {"error": "AVATARTALK_API_KEY is not set"}, status_code=500
            )
        meeting_token = sessions[session_id]["avatar_token"]
        try:
            _send_text_to_avatar_via_ws(
                meeting_token=meeting_token,
                text=assistant_text,
                avatar=avatar_v,
                emotion=emotion_v,
                language=language_v,
                increase_resolution=inc_res,
            )
        except Exception as e:
            return JSONResponse(
                {
                    "user_text": user_text,
                    "assistant_text": assistant_text,
                    "warning": f"avatar stream error: {e}",
                }
            )

        return JSONResponse(
            {
                "user_text": user_text,
                "assistant_text": assistant_text,
            }
        )
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


# WebSocket audio relay: browser -> server -> AvatarTalk /ws/infer (audio input)
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
import websockets


@app.websocket("/ws/audio")
async def ws_audio(
    websocket: WebSocket,
    session_id: str,
    avatar: str = "",
    emotion: str = "",
    language: str = "",
    increase_resolution: str = "false",
):
    await websocket.accept()
    try:
        _cleanup_sessions()
        if session_id not in sessions:
            await websocket.close(code=4000)
            return
        if not settings.avatartalk_api_key:
            await websocket.close(code=4001)
            return
        meeting_token = sessions[session_id]["avatar_token"]
        inc_res = str(increase_resolution).lower() in {"1", "true", "yes", "on"}
        base = settings.avatartalk_base_url.rstrip("/")
        qs = (
            f"output_type=livekit&input_type=audio&avatar={quote(avatar or settings.avatar)}"
            f"&emotion={quote(emotion or settings.emotion)}&language={quote(language or settings.language)}"
            f"&meeting_token={quote(meeting_token)}"
            f"&increase_resolution={'true' if inc_res else 'false'}"
        )
        up_url = f"{base}/ws/infer?{qs}"

        async with websockets.connect(
            up_url,
            extra_headers=[("Authorization", f"Bearer {settings.avatartalk_api_key}")],
            max_size=None,
        ) as upstream:
            # Relay browser binary frames to upstream
            async def from_client_to_upstream():
                while True:
                    data = await websocket.receive_bytes()
                    await upstream.send(data)

            # Optionally read upstream to keep connection healthy
            async def from_upstream_to_client():
                try:
                    async for _ in upstream:
                        # AvatarTalk may send small status frames; ignore
                        pass
                except Exception:
                    pass

            t1 = asyncio.create_task(from_client_to_upstream())
            t2 = asyncio.create_task(from_upstream_to_client())
            done, pending = await asyncio.wait(
                {t1, t2}, return_when=asyncio.FIRST_EXCEPTION
            )
            for t in pending:
                t.cancel()
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
