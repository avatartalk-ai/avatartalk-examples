# AvatarTalk Knowledge Base (Node.js)

A small Express demo that lets you chat with an avatar whose answers are grounded in your own documents. On each start, it builds a temporary OpenAI vector store from files in a local folder and then:

- Answers your questions using OpenAI with `file_search` over your uploaded files
- Generates a talking‑head video for each assistant reply via AvatarTalk
- Supports both text chat and push‑to‑talk voice input
- Offers real‑time video streaming or regular (non‑streaming) generation

This app is intended as a simple demonstration of AvatarTalk’s capabilities.

## What You Can Do

- Place files in `nodejs/knowledge-base/data` to seed the knowledge base
- Ask questions in the UI; answers are grounded via OpenAI `file_search`
- Pick avatar, emotion, and language for responses
- Use push‑to‑talk to speak your question and get a video answer
- Toggle “Stream video in real time” to watch the MP4 as it’s generated

## Requirements

- Node.js >= 18
- OpenAI API key with access to vector stores / `file_search`
- AvatarTalk API key
- Internet access for OpenAI and AvatarTalk APIs

## Setup

In `nodejs/knowledge-base`, copy the example env and fill in your keys:

```bash
cp .env.example .env
# Edit .env and set at least:
#   OPENAI_API_KEY=...
#   AVATARTALK_API_KEY=...
```

Optional: adjust defaults like `OPENAI_MODEL`, `AVATARTALK_AVATAR`, `AVATARTALK_LANGUAGE`, `KNOWLEDGE_BASE_DIRECTORY_PATH`, `VECTOR_STORE_NAME`.

Place your reference files (PDF, CSV, text, etc.) in `nodejs/knowledge-base/data` or point `KNOWLEDGE_BASE_DIRECTORY_PATH` to a different folder.

## Run

```bash
npm install
npm start
```

By default the app runs at: http://127.0.0.1:8000/

The home page provides a minimal chat UI with avatar controls, a push‑to‑talk button, and a streaming toggle.

## How It Works

- On startup, the app loads environment settings and creates a fresh OpenAI vector store (named by `VECTOR_STORE_NAME`).
- All files from `KNOWLEDGE_BASE_DIRECTORY_PATH` are uploaded into the store.
- Each chat turn uses OpenAI Responses with the `file_search` tool over that vector store to ground the assistant’s answer.
- The final assistant text is sent to AvatarTalk to synthesize a talking‑head video (either via returned MP4/HTML URLs or streamed in real time).
- On shutdown, the temporary vector store is deleted.

## Configuration

OpenAI

- `OPENAI_API_KEY` (required)
- `OPENAI_MODEL` (default: `gpt-4o-mini`)
- `OPENAI_STT_MODEL` (speech‑to‑text, default: `whisper-1`)

AvatarTalk

- `AVATARTALK_API_KEY` (or `AT_API_KEY`) (required)
- `AVATARTALK_API_BASE` (default: `https://api.avatartalk.ai`)
- `AVATARTALK_AVATAR` (e.g., `european_woman`, `japanese_man`, ...)
- `AVATARTALK_EMOTION` (`neutral`, `happy`, `serious`)
- `AVATARTALK_LANGUAGE` (e.g., `en`, `es`, `fr`, ...)
- `AVATARTALK_DELAYED` (`true` to defer generation until the URL is opened)

Knowledge Base

- `KNOWLEDGE_BASE_DIRECTORY_PATH` (default: `./data`)
- `VECTOR_STORE_NAME` (default: `avatartalk_knowledge_base`)

App Server

- `APP_HOST` (default: `127.0.0.1`)
- `APP_PORT` (default: `8000`)
- `APP_DEBUG` (default: `true`)

## Notes

- The vector store is ephemeral for this demo — restarts rebuild it from your `data` folder.
- Accessing `mp4_url`/`html_url` consumes credits on AvatarTalk.
- This demo calls paid APIs (OpenAI and AvatarTalk). Ensure your keys are valid and you understand billing.
