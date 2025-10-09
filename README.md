# avatartalk-examples

Example integrations with AvatarTalk.ai’s REST API for generating talking avatar videos from text. This repo includes Node.js and Python examples for regular (JSON), streaming (binary MP4), and LiveKit.

A live demo of the examples is available at https://demo.avatartalk.ai/.

Full documentation of AvatarTalk.ai API is available in [API.md](/API.md).

## Directories
- `nodejs` – Node 18+ examples using built-in `fetch` and streams
- `python` – Python examples managed with `uv` and using `requests`

## Examples Included

- `python/simple-webchat` – Text-first web chat (FastAPI) with optional voice input and streaming playback via server proxy.
- `python/livekit-webchat` – LiveKit-based webchat: assistant replies are spoken by an avatar into a LiveKit room via `/ws/infer`.
- `python/livekit-agents` – LiveKit Agents integration.
- `python/youtube-rtmp-streamer` – Generates short English‑learning segments with OpenAI and streams them to a YouTube Live RTMP endpoint via AvatarTalk; can read live chat and adapt topics.
- `python/knowledge-base` – Knowledge-grounded chat that builds an OpenAI vector store from local files and uses `file_search` to ground answers before rendering an avatar video.
- `nodejs/simple-webchat` – Feature-parity Node.js port (Express) of the text-first app, including voice input and streaming proxy.
- `nodejs/livekit-webchat` – Node.js LiveKit webchat where the assistant speaks into a LiveKit room via `/ws/infer`.
- `nodejs/youtube-rtmp-streamer` – Node.js RTMP streamer; same behavior as the Python version, streams to YouTube and adapts to live chat.
- `nodejs/knowledge-base` – Knowledge-grounded chat that builds an OpenAI vector store from local files and uses `file_search` to ground answers before rendering an avatar video.

## Key Endpoints

- `POST https://api.avatartalk.ai/inference` – returns JSON with `mp4_url` and `html_url`
- `POST https://api.avatartalk.ai/inference?stream=true` – returns MP4 video data streamed in real time
- Authentication: add header `Authorization: Bearer {YOUR_API_KEY}`

### Parameters (body)

- `text` (string, required) – text to be spoken
- `avatar` (string, required) – avatar identifier (e.g., `african_man`)
- `emotion` (string, required) – e.g., `neutral`, `happy`
- `language` (string, required) – e.g., `en`, `es`, `fr`, etc.
- `delayed` (boolean, optional) – if true, returns trigger URLs without upfront processing

### Notes

- The `mp4_url` and `html_url` returned by the regular endpoint are trigger URLs. On first access, they generate the video and consume credits; subsequent loads will serve cached content.

#### RTMP Examples

- See `python/youtube-rtmp-streamer` and `nodejs/youtube-rtmp-streamer` for streaming to YouTube Live via AvatarTalk.

## How To Run

- Python app (`python/simple-webchat`)
  - Requirements: `python>=3.10`, `uv`
  - Create `.env` with `OPENAI_API_KEY` and `AVATARTALK_API_KEY`
  - Run: `uv run simple-webchat`
  - Open `http://127.0.0.1:8000`

- Python app (`python/livekit-webchat`)
  - Requirements: `python>=3.10`, `uv`
  - Create `.env` with: `OPENAI_API_KEY`, `AVATARTALK_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
  - Run: `uv run livekit-webchat`
  - Open `http://127.0.0.1:8000` and chat (joins a LiveKit room and plays avatar media)

- Python app (`python/livekit-agents`)
  - Requirements: Access to LiveKit Agents repository with AvatarTalk integration branch
  - Provides real-time AI avatar conversations using LiveKit Agents framework

- Node.js app (`nodejs/simple-webchat`)
  - Requirements: `node>=18`
  - Copy env: `cp .env.example .env`, then set `OPENAI_API_KEY` and `AVATARTALK_API_KEY`
  - In the folder: `npm install` then `npm start`
  - Open `http://127.0.0.1:8000`

- Node.js app (`nodejs/livekit-webchat`)
  - Requirements: `node>=18`
  - Copy env: `cp .env.example .env`, then set `OPENAI_API_KEY`, `AVATARTALK_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
  - In the folder: `npm install` then `npm start`
  - Open `http://127.0.0.1:8000` and chat (joins a LiveKit room and plays avatar media)

- Python app (`python/youtube-rtmp-streamer`)
  - Requirements: `python=3.13`, `uv`
  - Create `.env` with: `OPENAI_API_KEY`, `AVATARTALK_API_KEY`, `AVATARTALK_AVATAR`, `YOUTUBE_RTMP_URL`, `YOUTUBE_STREAM_KEY`, `YOUTUBE_API_KEY` (optional: `YOUTUBE_LIVE_ID`)
  - In the folder: `uv sync`
  - Run: `uv run python main.py <VIDEO_ID>` or set `YOUTUBE_LIVE_ID` and run `uv run python main.py`

- Node.js app (`nodejs/youtube-rtmp-streamer`)
  - Requirements: `node>=18`
  - Copy env: `cp .env.example .env`, then set: `OPENAI_API_KEY`, `AVATARTALK_API_KEY`, `YOUTUBE_API_KEY`, `YOUTUBE_RTMP_URL`, `YOUTUBE_STREAM_KEY` (optional: `YOUTUBE_LIVE_ID`)
  - In the folder: `npm install`
  - Run: `node src/main.js <VIDEO_ID>` or set `YOUTUBE_LIVE_ID` and run `node src/main.js`

- Python app (`python/knowledge-base`)
  - Requirements: `python>=3.10`, `uv`
  - Create `.env` with `OPENAI_API_KEY` and `AVATARTALK_API_KEY`
  - Place files in `data/` (or set `KNOWLEDGE_BASE_DIRECTORY_PATH`)
  - Run: `uv run knowledge-base`
  - Open `http://127.0.0.1:8000`

- Node.js app (`nodejs/knowledge-base`)
  - Requirements: `node>=18`
  - Copy env: `cp .env.example .env`, then set `OPENAI_API_KEY` and `AVATARTALK_API_KEY`
  - Place files in `data/` (or set `KNOWLEDGE_BASE_DIRECTORY_PATH`)
  - In the folder: `npm install` then `npm start`
  - Open `http://127.0.0.1:8000`
