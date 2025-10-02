# AvatarTalk - YouTube RTMP streamer

A small application that generates short English‑learning segments with OpenAI and streams them via AvatarTalk to a YouTube Live RTMP endpoint. It can also read live chat and adapt topics accordingly.

## Quick Start
1) Requirements: Python 3.13 and uv.

2) Install:
- `uv sync`
- `pre-commit install`

3) Configure `.env` (placeholders):
```
OPENAI_API_KEY=sk-...
AVATARTALK_URL=wss://api.avatartalk.ai
AVATARTALK_API_KEY=...
AVATARTALK_AVATAR=
YOUTUBE_RTMP_URL=rtmp://a.rtmp.youtube.com/live2
YOUTUBE_STREAM_KEY=...
YOUTUBE_API_KEY=...
AVATARTALK_LANGUAGE=...
# Optional if not passing via CLI
YOUTUBE_LIVE_ID=<VIDEO_ID>
AVATARTALK_TOPICS_FILE=topics.txt
```

## Run
- With CLI argument: `uv run python main.py <VIDEO_ID>`
- Using env fallback: set `YOUTUBE_LIVE_ID` and run `uv run python main.py`

The generated speaking segment is printed to stdout (for TTS/pipe usage). Operational logs go to stderr.

