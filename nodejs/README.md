# Node.js Examples

## Projects

- `nodejs/simple-webchat` – Full web chat (Express + Nunjucks) with text chat, push‑to‑talk transcription, and optional streaming playback via a server proxy.
- `nodejs/livekit-webchat` – LiveKit webchat where the assistant speaks into a LiveKit room via `/ws/infer`.
- `nodejs/youtube-rtmp-streamer` – Generates short English‑learning segments with OpenAI and streams them to a YouTube Live RTMP endpoint via AvatarTalk; can read live chat and adapt topics.

## Quick start (simple-webchat)

- `cd nodejs/simple-webchat`
- `cp .env.example .env` and set `OPENAI_API_KEY`, `AVATARTALK_API_KEY`
- `npm install`
- `npm start`
- Open `http://127.0.0.1:8000`

## Quick start (livekit-webchat)

- `cd nodejs/livekit-webchat`
- `cp .env.example .env` and set `OPENAI_API_KEY`, `AVATARTALK_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- `npm install`
- `npm start`
- Open `http://127.0.0.1:8000`

## Quick start (youtube-rtmp-streamer)

- `cd nodejs/youtube-rtmp-streamer`
- `cp .env.example .env` and set at least: `OPENAI_API_KEY`, `AVATARTALK_API_KEY`, `YOUTUBE_API_KEY`, `YOUTUBE_RTMP_URL`, `YOUTUBE_STREAM_KEY`
- Optional: set `YOUTUBE_LIVE_ID` (otherwise pass `<VIDEO_ID>` on CLI)
- `npm install`
- `node src/main.js <VIDEO_ID>` or set `YOUTUBE_LIVE_ID` and run `node src/main.js`
