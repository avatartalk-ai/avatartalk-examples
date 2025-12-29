# AvatarTalk · LiveKit WebChat (Python, uv app)

## Overview

- LiveKit-based chat: user types or speaks; OpenAI generates assistant replies; AvatarTalk speaks them into a LiveKit room via `/ws/infer?output_type=livekit`.
- Push-to-talk: hold the mic to record; speech is transcribed with OpenAI; the assistant reply is then spoken in-room.
- Optional low-latency: enable "Stream audio" to relay mic chunks directly to AvatarTalk via a server WebSocket proxy; avatar speaks in real-time into the room.
- Frontend joins the LiveKit room (subscribe to avatar tracks). No file endpoints or MP4 playback.
- Stack: FastAPI + Jinja2, `openai` (chat+STT), `PyJWT` (LiveKit JWT), `websocket-client` (bridge to AvatarTalk WS), `python-dotenv`.

### Environment variables

- `OPENAI_API_KEY` (required) – OpenAI API key
- `OPENAI_MODEL` (optional, default: `gpt-4o-mini`)
- `OPENAI_STT_MODEL` (optional, default: `whisper-1`)
- `AVATARTALK_API_KEY` (required) – AvatarTalk API key
- `AVATARTALK_API_BASE` (optional, default: `wss://api.avatartalk.ai`)
- `AVATARTALK_AVATAR` (optional, default: `european_woman`)
- `AVATARTALK_EMOTION` (optional, default: `neutral`)
- `AVATARTALK_LANGUAGE` (optional, default: `en`)
- `APP_HOST` (optional, default: `127.0.0.1`)
- `APP_PORT` (optional, default: `8000`)
- `APP_DEBUG` (optional, default: `true`)
- `LIVEKIT_URL` (required) – LiveKit server WebSocket URL, e.g. `wss://your-livekit.example.com`
- `LIVEKIT_API_KEY` (required) – LiveKit API key used for JWT minting
- `LIVEKIT_API_SECRET` (required) – LiveKit API secret used for JWT signing
- `LIVEKIT_TOKEN_TTL` (optional, default: `3600`) – seconds tokens are valid

This app loads `.env` automatically using `python-dotenv`.

## Quick Start

1) Ensure Python 3.10+ and install `uv`
2) In this folder (`python/livekit-webchat`), create a `.env` with at least:
   - `OPENAI_API_KEY=sk-...`
   - `AVATARTALK_API_KEY=at_...`
   - `LIVEKIT_URL=wss://...`
   - `LIVEKIT_API_KEY=...`
   - `LIVEKIT_API_SECRET=...`
3) Run the app:
   - `uv run livekit-webchat`
   - Or: `uv run uvicorn livekit_webchat.app:app --reload --port 8000`
4) Open http://127.0.0.1:8000 and chat.
   - The page auto-creates a LiveKit session and joins the room.
   - Type text or use push-to-talk; the avatar speaks the assistant reply in-room.

#### Notes

- We mint two LiveKit tokens per session: one for the browser (subscribe-only) and one for the avatar publisher (kept server-side and passed as `meeting_token` to `/ws/infer`).
- The server bridges the `/ws/infer` call to include `Authorization: Bearer <AVATARTALK_API_KEY>`.
- Audio recording uses `MediaRecorder` (WebM/Opus) when supported; Safari may fall back to different MIME types. The app adapts filename accordingly.

## Layout

- `src/livekit_webchat/app.py` – FastAPI app and routes
  - Endpoints: `GET /` (UI), `POST /session` (mint room + user token), `POST /chat` (OpenAI + send to LiveKit via `/ws/infer`), `POST /voice`, `POST /transcribe`
- `src/livekit_webchat/config.py` – env loading and settings (OpenAI, AvatarTalk, LiveKit)
- `src/livekit_webchat/openai_client.py` – OpenAI chat + transcription helpers
- `GET /session` – mints user token (subscribe-only) and internal avatar token (publish-only) using official `livekit` SDK
- `WS /ws/audio` – server WS relay for streaming mic audio chunks to `/ws/infer?output_type=livekit&input_type=audio`
- `templates/index.html` – chat UI + LiveKit join/subscription
