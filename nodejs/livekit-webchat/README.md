# AvatarTalk · LiveKit WebChat (Node.js)

## Overview

- LiveKit-based chat: user types or speaks; OpenAI generates assistant replies; AvatarTalk speaks them into a LiveKit room via `/ws/infer?output_type=livekit`.
- Push-to-talk: hold mic to record; speech is transcribed with OpenAI; the assistant reply is then spoken in-room.
- Optional low-latency: enable "Stream audio" to relay mic chunks directly to AvatarTalk via a server WebSocket proxy; avatar speaks in real-time into the room.
- Frontend joins the LiveKit room (subscribe to avatar tracks). No file endpoints or MP4 playback.
- Stack: Express + Nunjucks, `openai` (chat+STT), `livekit-server-sdk` (JWT + optional room create), `ws` (WebSocket bridge), `dotenv`.

### Environment variables

- `OPENAI_API_KEY` (required) – OpenAI API key
- `OPENAI_MODEL` (optional, default: `gpt-4o-mini`)
- `OPENAI_STT_MODEL` (optional, default: `whisper-1`)
- `AVATARTALK_API_KEY` (required) – AvatarTalk API key
- `AVATARTALK_API_BASE` (optional, default: `https://api.avatartalk.ai`)
- `AVATARTALK_WS_BASE` (optional, default: `wss://avatartalk.ai`)
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

## Quick Start

1) Ensure Node 18+ (uses built-in fetch + WHATWG streams)
2) `cd nodejs/livekit-webchat`
3) Copy and fill env:
   - `cp .env.example .env`
   - Set `OPENAI_API_KEY`, `AVATARTALK_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
4) `npm install`
5) `npm start`
6) Open http://127.0.0.1:8000 and chat

### Notes

- Two tokens per session are minted: one for the browser (subscribe-only) and one for the avatar publisher (kept server-side and passed as `meeting_token` to `/ws/infer`).
- The server bridges the `/ws/infer` call to include `Authorization: Bearer <AVATARTALK_API_KEY>`.
- Audio recording uses `MediaRecorder` (WebM/Opus) when supported; Safari may fall back to different MIME types. The app adapts filename accordingly.

## Layout

- `src/app.js` – Express app and routes
  - Endpoints: `GET /` (UI), `POST /session` (mint room + user token), `POST /chat` (OpenAI + send to LiveKit via `/ws/infer`), `POST /voice`, `POST /transcribe`
- `src/config.js` – env loading and settings (OpenAI, AvatarTalk, LiveKit)
- `src/openai_client.js` – OpenAI chat + transcription helpers
- `src/avatartalk_ws.js` – helper to send text via `/ws/infer?output_type=livekit`
- `templates/index.html` – chat UI + LiveKit join/subscription
