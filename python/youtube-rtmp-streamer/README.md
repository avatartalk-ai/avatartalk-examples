# AvatarTalk — YouTube RTMP Streamer

Small Python app that generates short language‑learning segments with OpenAI and streams them via AvatarTalk to a YouTube Live RTMP endpoint. Supports multiple languages. It can also read live chat, adapt the next topic accordingly, and post generated responses back to the live chat.

## Quick Start
- Requirements: Python 3.13, `uv`.
- Install deps: `uv sync`
- Set up YouTube OAuth2 credentials (see below).
- Create `.env` with your keys (see below).
- Start automatically: `./run_streamer.sh` (English, circular background). No broadcast ID or RTMP key needed.

## YouTube Setup

### RTMP Streaming
- RTMP URL: use `rtmp://a.rtmp.youtube.com/live2` unless YouTube tells you otherwise.
- Stream key: in YouTube Studio → Go live → Stream → Stream key.

### YouTube Data API v3 (OAuth2)
This app uses OAuth2 authentication to read live chat comments and post responses back to chat. You'll need to create OAuth2 credentials in Google Cloud Console:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable "YouTube Data API v3" for your project
4. Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client ID"
5. Choose "Desktop app" as the application type
6. Download the JSON file and save it (e.g., as `gcp_youtube_oauth_key.json`)
7. Set `GOOGLE_CLIENT_SECRETS_PATH` in `.env` to point to this file
8. On first run, the app will open a browser window for OAuth2 authorization
9. You'll also need a YouTube API key (`YOUTUBE_API_KEY`) for certain read operations

## Configuration (.env)
Set these environment variables in a `.env` file next to `main.py`:

```bash
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

# YouTube broadcast ID and RTMP URL/key are discovered/created through OAuth.
# Legacy YOUTUBE_LIVE_ID, YOUTUBE_RTMP_URL, YOUTUBE_STREAM_KEY and stream_keys.json are ignored.

# YouTube Data API v3 (required to read/post live chat)
YOUTUBE_API_KEY=...
# Path to OAuth2 credentials JSON file (required for chat posting)
GOOGLE_CLIENT_SECRETS_PATH=gcp_youtube_oauth_key.json


```

## Run

### Manual Mode
- With explicit video ID: `uv run python main.py <VIDEO_ID>`
- Automatic discovery/creation: `uv run python main.py` (old `YOUTUBE_LIVE_ID` values are ignored)
- Optional background image: add `--background-url <https-url>`
- Specify language: add `--language <code>` (default: `en`)
- Adjust logging: `--log-level DEBUG|INFO|WARNING|ERROR|CRITICAL`
- Skip welcome messages: add `--skip-welcome` (useful when manually restarting)

The generated speaking segment is printed to stdout (handy for piping/testing). Operational logs go to stderr. Press Ctrl+C to stop gracefully.

**Note:** On first run, the app will open a browser window for OAuth2 authorization to access YouTube live chat. This is required for posting responses back to the chat.

### Infinite Restart Mode (Production)
For production use, we provide a bash script that automatically restarts the streamer if it crashes.
Its default background is `feng_shui_2.png` (circular avatar window); the third argument overrides it:

```bash
./run_streamer.sh <VIDEO_ID> <LANGUAGE> [BACKGROUND_URL]
```

**Examples:**
```bash
# Basic usage with English
./run_streamer.sh dQw4w9WgXcQ en

# With custom background
./run_streamer.sh dQw4w9WgXcQ es https://avatartalk.ai/images/backgrounds/gym_1.png

# French stream
./run_streamer.sh abc123 fr
```

**Features:**
- **Auto-restart**: Automatically restarts the streamer if it crashes
- **Smart welcome detection**: Automatically detects if welcome messages were already posted and skips them on restart
- **Crash protection**: Exits after 10 crashes to prevent infinite error loops
- **Colored output**: Easy-to-read status messages with color coding
- **Exit code handling**: Different behavior based on exit codes (normal exit, crash, config error, etc.)
- **Runtime tracking**: Shows how long each session ran before exit
- **Graceful shutdown**: Press Ctrl+C to stop the restart loop

**Exit Codes:**
- `0`: Normal exit → Restarts in 5 seconds
- `1`: Crash → Restarts in 10 seconds (or 30s if crash was very quick)
- `2`: Configuration error → Exits immediately (fix config and restart manually)
- `130`: User interrupt (Ctrl+C) → Exits gracefully

This script is recommended for production streams where you want the stream to continue even if there are temporary issues.

## Backgrounds

Here's the list of available backgrounds provided by AvatarTalk.ai:
- https://avatartalk.ai/images/backgrounds/feng_shui_1.png (square; direct Python default)
- https://avatartalk.ai/images/backgrounds/feng_shui_2.png (circular; `run_streamer.sh` default)

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

## CLI Options
- `video_id` (positional, optional): explicitly target a YouTube broadcast. Without it, find an existing broadcast for the language or create one, creating/binding an RTMP stream if needed. Missing/finished explicit IDs fail rather than silently targeting another video.
- `--background-url`: HTTPS URL for a background image in the RTMP stream.
- `--language`: Language code for speech synthesis (default: `en`).
- `--log-level`: Logging verbosity (default: `INFO`).

## How It Works
- Uses the authenticated YouTube channel to find a matching active/ready broadcast, or creates a public broadcast with automatic start. Resumes an existing broadcast on restart.
- Reuses the selected broadcast's bound RTMP stream. If unbound, reuses/creates an `AvatarTalk <language> RTMP` stream and binds it automatically. API/auth failures stop startup rather than creating duplicate broadcasts.
- Reads recent YouTube Live chat messages (if available) via YouTube Data API v3.
- Autonomously generates fresh conversation topics and segments using rolling memory of previously covered concepts and live chat context so it never loops.
- Loads system prompts from `narration.prompt` (for avatar monologues) and `chat.prompt` (for chat responses).
- Both prompts use `{language}` placeholder, which is replaced with the full language name based on `--language` flag.
- Targets 60–70 words per narration segment, aiming for about 30 seconds of speech (not a duration guarantee; voice/language/rate and the appended 2-second silence affect actual duration). Generates the next segment with 15 seconds of estimated playback left and sends it with 10 seconds left, covering the renderer's ~4.8-second audio window plus synthesis/render jitter.
- Playback estimates add each acknowledged duration to the existing timeline, not to the acknowledgement time, avoiding cumulative TTS round-trip drift. Lookahead is bounded; reconnects reset the estimate. This is a client-side schedule, not a measurement of actual RTMP delivery. Longer segments/lookahead also mean spoken responses to new chat messages may be delayed.
- Sends it to the AvatarTalk WebSocket RTMP gateway, which renders the avatar and streams to YouTube.
- Responds to viewer questions using the chat prompt and posts responses back to YouTube Live chat in chunks (max 200 characters per message).

### YouTube guidance

- [Encoder settings](https://support.google.com/youtube/answer/2853702?hl=en): keyframes every 2 seconds are recommended (maximum 4 seconds), with CBR. This keyframe interval is not a limit on narration length; RTMP carries continuous encoded audio/video, not the text requests.
- [Streaming latency](https://support.google.com/youtube/answer/7444635?hl=en): ultra-low latency leaves less read-ahead buffer and is more prone to buffering; low latency offers a more forgiving trade-off. This change does not alter the broadcast latency setting or the renderer.

## Troubleshooting
- **Repeated offline/buffering**: YouTube `videoIngestionStarved` means insufficient incoming video even when ingest is `active`. The streamer logs ingest health/issues separately from connection status. Longer segments and earlier submission reduce client-side starvation, but cannot enforce server-side RTMP pacing or fix a slow renderer/network. No GeneFace changes are included in this client fix.
- **"YOUTUBE_API_KEY not provided"**: Set `YOUTUBE_API_KEY` and ensure YouTube Data API v3 is enabled.
- **"GOOGLE_CLIENT_SECRETS_PATH not set!"**: You need OAuth2 credentials for posting to chat. See "YouTube Setup" above.
- **OAuth2 browser window doesn't open**: Make sure you're running on a machine with a browser. The credentials are cached after first authorization.
- **No comments detected**: Confirm the stream is live and the `VIDEO_ID` is correct; check that the channel has an active live chat.
- **Cannot post to chat**: Verify OAuth2 authorization was successful and the account has permission to post to the channel's live chat.
- **WebSocket/auth errors**: Verify `AVATARTALK_API_KEY`, `AVATARTALK_AVATAR`, and RTMP settings.
- **Upcoming / no video on YouTube**: A chat connection or AvatarTalk duration acknowledgement does not confirm video delivery. The streamer resolves the selected broadcast's bound ingest credentials via OAuth and polls YouTube even during narration. `noData` means YouTube is not receiving that stream; `ready`/`testing` with active ingest is advanced toward `live`. Restart the process after changing code or ingest configuration; an already-open connector keeps its old destination.

