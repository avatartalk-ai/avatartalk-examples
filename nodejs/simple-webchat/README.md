# AvatarTalk · Simple WebChat (Node.js)

## Overview

- Text-first demo: user types a message, OpenAI generates the assistant reply, and AvatarTalk renders that reply as an avatar video via `/inference`.
- Push-to-talk: hold the mic button to record; on release, audio is transcribed with OpenAI, then routed through the same reply + `/inference` flow.
- Streaming option: enable the checkbox to stream MP4 in real-time via `/inference?stream=true` proxied by the server; otherwise use regular JSON response with `mp4_url/html_url`.
  - The player autoplays when a new video or stream is ready.
- Stack: Express + Nunjucks, `openai`, `dotenv`, `multer`.

### Environment variables

- `OPENAI_API_KEY` (required) – OpenAI API key
- `OPENAI_MODEL` (optional, default: `gpt-4o-mini`)
- `OPENAI_STT_MODEL` (optional, default: `whisper-1`)
- `AVATARTALK_API_KEY` (required) – AvatarTalk API key
- `AVATARTALK_API_BASE` (optional, default: `https://api.avatartalk.ai`)
- `AVATARTALK_AVATAR` (optional, default: `european_woman`)
- `AVATARTALK_EMOTION` (optional, default: `neutral`)
- `AVATARTALK_LANGUAGE` (optional, default: `en`)
- `AVATARTALK_DELAYED` (optional, default: `false`) – if true, returns trigger URLs without upfront processing
- `APP_HOST` (optional, default: `127.0.0.1`)
- `APP_PORT` (optional, default: `8000`)
- `APP_DEBUG` (optional, default: `true`)

This app loads `.env` automatically using `dotenv`.

## Quick Start

1) Ensure Node.js 18+
2) In this folder (`nodejs/simple-webchat`), copy the example env and fill in your keys:
   - `cp .env.example .env`
   - Set `OPENAI_API_KEY=sk-...` and `AVATARTALK_API_KEY=at_...`
3) Install deps and run:
   - `npm install`
   - `npm start`
4) Open http://127.0.0.1:8000 and chat.
   - Type text and click Send, or hold the mic button to talk.
   - Toggle "Stream video in real time" to use streaming MP4; otherwise, non-streaming URLs are returned.

### Notes

- The `mp4_url`/`html_url` are trigger URLs; first access generates the video and consumes credits.
- Streaming uses a server-side proxy endpoint (`/stream/{id}.mp4`) that initializes AvatarTalk `/inference?stream=true` and streams chunks to the browser.
  - Pending stream IDs are auto-cleaned with a ~10-minute TTL.
- Audio recording uses `MediaRecorder` (WebM/Opus) when supported; Safari may fall back to different MIME types. The app adapts filename accordingly.
- For voice input, the transcription is shown immediately after upload, then assistant text is generated and video is started (streaming or regular) based on the toggle.

## Layout

- `src/app.js` – Express app and routes
  - Endpoints: `GET /`, `GET /healthz`, `POST /chat`, `POST /voice`, `POST /transcribe`, `POST /chat_stream`, `GET /stream/{id}.mp4`
- `src/config.js` – env loading and settings
- `src/openai_client.js` – OpenAI chat + transcription helpers
- `src/avatartalk_client.js` – calls `/inference`
- `templates/index.html` – minimal chat UI (same as Python version)
