# API Reference

## WebSocket Endpoints

### Client ↔ Browser (`ws://localhost:8080/ws/conversation`)

**Browser → Client (Text Frames)**
```json
{"type": "init", "data": {"avatar": "european_woman", "expression": "neutral", "prompt": "...", "use_pregen": true}}
{"type": "audio_config", "data": {"sample_rate": 48000, "channel_count": 1}}
{"type": "buffer_status", "data": {"buffered_ms": 450, "playback_position": 1.5}}
```

**Browser → Client (Binary Frames)**
- Raw linear16 PCM audio chunks (~80ms)

**Client → Browser (Text Frames)**
```json
{"type": "session_ready", "data": {"session_id": "..."}}
{"type": "status", "data": "listening"}  // or "thinking", "speaking"
```

**Client → Browser (Binary Frames)**
- Raw MP4 video chunks (feed to MediaSource)

---

### Client ↔ AvatarTalk API (`wss://api.avatartalk.ai/ws/continuous`)

**Connection**
- Query params: `?avatar=...&expression=...&language=...`
- Header: `Authorization: Bearer <AVATARTALK_API_KEY>`

**Client → AvatarTalk (Text Frames)**
```json
{"type": "session_start", "data": {"avatar_name": "...", "expression": "...", "language": "en", "expressive_mode": false}}
{"type": "turn_start", "data": {"expression": "happy"}}
{"type": "text_input", "data": {"text": "...", "expression": "...", "mode": "dynamic_only"}}
{"type": "text_append", "data": {"text": "..."}}
{"type": "text_stream_done", "data": {}}
{"type": "buffer_status", "data": {"buffered_ms": 450, "playback_position": 1.5}}
```

**AvatarTalk → Client (Text Frames)**
```json
{"type": "session_ready", "data": {"session_id": "..."}}
{"type": "state_change", "data": {"from": "silence", "to": "pregen_video"}}
{"type": "ready_to_listen", "data": {"timestamp": ...}}
{"type": "error", "data": {"message": "..."}}
```

**AvatarTalk → Client (Binary Frames)**
- Raw MP4 video chunks

## State Machine

The AvatarTalk API manages avatar state transitions:

```
SILENCE → text_input → PREGEN → DYNAMIC_SPEECH → SILENCE
```

Key states:
- `silence` – Avatar idle, looping silence video
- `pregen_video` – Playing pregenerated transition
- `dynamic_speech` – Avatar speaking generated content
- `ready_to_listen` – Signal to enable microphone

## Performance

| Metric | Value |
|--------|-------|
| End-to-End Latency | < 1000ms |
| Turn Detection | ~500ms (Deepgram Flux) |
| Video Buffer | 300-500ms target |
