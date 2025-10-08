# AvatarTalk - YouTube RTMP streamer (Node.js)

A small Node.js application that generates short English‑learning segments with OpenAI and streams them via AvatarTalk to a YouTube Live RTMP endpoint. It can also read live chat and adapt topics accordingly.

## Quick Start
1) Requirements: Node.js 18+ and npm.

2) Install:
- `cd nodejs/youtube-rtmp-streamer`
- `npm install`

3) Configure environment:
- Copy `.env.example` to `.env` and fill in values

Required keys:
- `OPENAI_API_KEY`
- `AVATARTALK_API_KEY`
- `YOUTUBE_API_KEY`
- `YOUTUBE_RTMP_URL` (e.g. `rtmp://a.rtmp.youtube.com/live2`)
- `YOUTUBE_STREAM_KEY`

Optional:
- `YOUTUBE_LIVE_ID` if you prefer not to pass the video id via CLI
- `AVATARTALK_AVATAR`, `AVATARTALK_LANGUAGE` (defaults provided)
- `AVATARTALK_TOPICS_FILE` (defaults to `topics.txt`)
- `AVATARTALK_MODEL` (defaults to `gpt-4o-mini`)

## Run
- With CLI argument: `node src/main.js -- <VIDEO_ID> --background-url <BACKGROUND_URL>`
- Using env fallback: set `YOUTUBE_LIVE_ID` and run `node src/main.js`
- Control logging: `--log-level DEBUG|INFO|WARNING|ERROR|CRITICAL` (default: INFO)

The generated speaking segment is printed to stdout (for TTS/pipe usage). Operational logs go to stderr.

## Backgrounds

Here's the list of available backgrounds provided by AvatarTalk.ai:
- https://avatartalk.ai/images/backgrounds/feng_shui_1.png (default)
- https://avatartalk.ai/images/backgrounds/feng_shui_2.png
- https://avatartalk.ai/images/backgrounds/feng_shui_3.png
- https://avatartalk.ai/images/backgrounds/feng_shui_4.png
- https://avatartalk.ai/images/backgrounds/feng_shui_5.png
- https://avatartalk.ai/images/backgrounds/dance_hall_1.png
- https://avatartalk.ai/images/backgrounds/dance_hall_2.png
- https://avatartalk.ai/images/backgrounds/dance_hall_3.png
- https://avatartalk.ai/images/backgrounds/dance_hall_4.png
- https://avatartalk.ai/images/backgrounds/dance_hall_5.png
- https://avatartalk.ai/images/backgrounds/gym_1.png
- https://avatartalk.ai/images/backgrounds/gym_2.png
- https://avatartalk.ai/images/backgrounds/gym_3.png
- https://avatartalk.ai/images/backgrounds/gym_4.png
- https://avatartalk.ai/images/backgrounds/gym_5.png
- https://avatartalk.ai/images/backgrounds/kitchen_1.png
- https://avatartalk.ai/images/backgrounds/kitchen_2.png
- https://avatartalk.ai/images/backgrounds/kitchen_3.png
- https://avatartalk.ai/images/backgrounds/kitchen_4.png
- https://avatartalk.ai/images/backgrounds/kitchen_5.png
- https://avatartalk.ai/images/backgrounds/template_1.png
- https://avatartalk.ai/images/backgrounds/template_2.png
- https://avatartalk.ai/images/backgrounds/template_3.png
- https://avatartalk.ai/images/backgrounds/template_4.png
- https://avatartalk.ai/images/backgrounds/template_5.png
- https://avatartalk.ai/images/backgrounds/temple_1.png
- https://avatartalk.ai/images/backgrounds/temple_2.png
- https://avatartalk.ai/images/backgrounds/temple_3.png
- https://avatartalk.ai/images/backgrounds/temple_4.png
- https://avatartalk.ai/images/backgrounds/temple_5.png

## How it works
- YouTube Data API is used to fetch recent live chat messages.
- Recent comments are summarized with OpenAI to guide the next topic.
- The content segment is generated with OpenAI Chat Completions.
- AvatarTalk is driven via WebSocket to synthesize and publish to your RTMP ingest URL/key.

## Project structure
- `src/config.js` — env configuration
- `src/youtube.js` — YouTube Data API client + summarization
- `src/avatartalk.js` — AvatarTalk WebSocket/RTMP connector
- `src/core.js` — main loop: topic selection, generation, streaming
- `src/main.js` — CLI entry
- `topics.txt` — default set of English‑learning topics

## Notes
- Ensure your YouTube Live event is set up and RTMP ingest is ready.
- The app waits between segments to avoid overlapping playback based on returned audio duration.
