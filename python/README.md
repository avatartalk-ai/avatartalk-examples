# Python Examples

- `python/simple-webchat` – Full web chat (FastAPI + Jinja2) with text chat, push‑to‑talk transcription, and optional streaming playback via a server proxy.
- `python/livekit-webchat` – LiveKit webchat where the assistant speaks into a LiveKit room via `/ws/infer`.
- `python/livekit-agents` - LiveKit Agents integration.
- `python/youtube-rtmp-streamer` – Generates short English‑learning segments with OpenAI and streams them to a YouTube Live RTMP endpoint via AvatarTalk; can read live chat and adapt topics.
- `python/knowledge-base` – Knowledge-grounded chat that builds an OpenAI vector store from local files and uses `file_search` to ground answers before rendering an avatar video.

## Quick start (simple-webchat)

- `cd python/simple-webchat`
- Ensure Python 3.10+ and install `uv`
- Create `.env` with `OPENAI_API_KEY` and `AVATARTALK_API_KEY`
- `uv run simple-webchat`
- Open `http://127.0.0.1:8000`

#### Notes

- Env vars and behavior mirror the Node.js version for parity.

## Quick start (livekit-webchat)

- `cd python/livekit-webchat`
- Ensure Python 3.10+ and install `uv`
- Create `.env` with at least: `OPENAI_API_KEY`, `AVATARTALK_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- `uv run livekit-webchat`
- Open `http://127.0.0.1:8000`

## Quick start (youtube-rtmp-streamer)

- `cd python/youtube-rtmp-streamer`
- Ensure Python 3.13 and install `uv`
- Create `.env` with at least: `OPENAI_API_KEY`, `AVATARTALK_API_KEY`, `AVATARTALK_AVATAR`, `YOUTUBE_RTMP_URL`, `YOUTUBE_STREAM_KEY`, `YOUTUBE_API_KEY` (optional: `YOUTUBE_LIVE_ID`)
- `uv sync`
- Run with CLI arg: `uv run python main.py <VIDEO_ID>` or set `YOUTUBE_LIVE_ID` and run `uv run python main.py`

## Quick start (knowledge-base)

- `cd python/knowledge-base`
- Ensure Python 3.10+ and install `uv`
- Create `.env` with `OPENAI_API_KEY` and `AVATARTALK_API_KEY`
- Place files in `data/` (or set `KNOWLEDGE_BASE_DIRECTORY_PATH`)
- `uv run knowledge-base`
- Open `http://127.0.0.1:8000`
