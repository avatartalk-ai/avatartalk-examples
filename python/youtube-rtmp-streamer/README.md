# AvatarTalk — YouTube RTMP Streamer

Small Python app that generates short English‑learning segments with OpenAI and streams them via AvatarTalk to a YouTube Live RTMP endpoint. It can also read live chat and adapt the next topic accordingly.

## Quick Start
- Requirements: Python 3.13, `uv`.
- Install deps: `uv sync`
- Create `.env` with your keys (see below).
- Start: `uv run python main.py <YOUTUBE_VIDEO_ID>`

If you omit the video ID, set `YOUTUBE_LIVE_ID` in `.env` and run `uv run python main.py`.

## YouTube Setup
- RTMP URL: use `rtmp://a.rtmp.youtube.com/live2` unless YouTube tells you otherwise.
- Stream key: in YouTube Studio → Go live → Stream → Stream key.
- Live Chat API: create an API key in Google Cloud and enable “YouTube Data API v3”. Set it as `YOUTUBE_API_KEY`.

## Configuration (.env)
Set these environment variables in a `.env` file next to `main.py`:

```
# OpenAI for content generation (required)
OPENAI_API_KEY=sk-...

# AvatarTalk RTMP gateway (API key required; URL optional)
AVATARTALK_API_KEY=...
# Optional: defaults to wss://api.avatartalk.ai
AVATARTALK_URL=wss://api.avatartalk.ai
# Avatar name as configured in your AvatarTalk account
AVATARTALK_AVATAR=...
# Spoken language (default: en)
AVATARTALK_LANGUAGE=en
# Model used for generation (default: gpt-4o-mini)
AVATARTALK_MODEL=gpt-4o-mini

# YouTube streaming (required to publish video)
YOUTUBE_RTMP_URL=rtmp://a.rtmp.youtube.com/live2
YOUTUBE_STREAM_KEY=...

# YouTube Live chat (required to read/summarize comments)
YOUTUBE_API_KEY=...

# Optional: set if you don’t pass the video ID via CLI
YOUTUBE_LIVE_ID=<VIDEO_ID>

# Topics file (must exist). Defaults to topics.txt in this folder
AVATARTALK_TOPICS_FILE=topics.txt
```

## Run
- With explicit video ID: `uv run python main.py <VIDEO_ID>`
- Using env fallback: `YOUTUBE_LIVE_ID=<VIDEO_ID> uv run python main.py`
- Optional background image: add `--background-url <https-url>`
- Adjust logging: `--log-level DEBUG|INFO|WARNING|ERROR|CRITICAL`

The generated speaking segment is printed to stdout (handy for piping/testing). Operational logs go to stderr. Press Ctrl+C to stop gracefully.

## CLI Options
- `video_id` (positional, optional): YouTube Live video ID. Falls back to `YOUTUBE_LIVE_ID`.
- `--background-url`: HTTPS URL for a background image in the RTMP stream.
- `--log-level`: Logging verbosity (default: `INFO`).

## How It Works
- Reads recent YouTube Live chat messages (if available) via YouTube Data API.
- Chooses a topic from chat summary or randomly from `topics.txt`.
- Generates a 60–90 word monologue with OpenAI.
- Sends it to the AvatarTalk WebSocket RTMP gateway, which renders the avatar and streams to YouTube.
- Uses a simple cooldown so segments don’t overlap while audio is playing.

## Troubleshooting
- “YOUTUBE_API_KEY not provided”: Set `YOUTUBE_API_KEY` and ensure YouTube Data API v3 is enabled.
- “Topics file ... not found”: Ensure `AVATARTALK_TOPICS_FILE` points to an existing file (default `topics.txt`).
- No comments detected: Confirm the stream is live and the `VIDEO_ID` is correct; check that the channel has an active live chat.
- WebSocket/auth errors: Verify `AVATARTALK_API_KEY`, `AVATARTALK_AVATAR`, and RTMP settings.
- No video on YouTube: Double‑check `YOUTUBE_RTMP_URL` and `YOUTUBE_STREAM_KEY`, and that the stream is started in YouTube Studio.

