# AvatarTalk API Documentation

## Base URL

`https://api.avatartalk.ai`

## Table of Contents

- [Base URL](#base-url)
- [Authentication](#authentication)
- [POST /inference](#post-inference)
- [WebSocket /ws/infer](#websocket-wsinfer)
- [WebSocket /ws/continuous](#websocket-wscontinuous)
- [LiveKit Session Management](#livekit-session-management)
  - [Create LiveKit Session](#create-livekit-session)
  - [Delete LiveKit Session](#delete-livekit-session)
- [Lightning Network Payment Endpoints](#lightning-network-payment-endpoints)
  - [Payment Flow Overview](#payment-flow-overview)
  - [POST /lightning/request-video/text](#post-lightningrequest-video-text)
  - [POST /lightning/request-video/audio](#post-lightningrequest-video-audio)
  - [POST /lightning/generate-video](#post-lightninggenerate-video)
  - [GET /lightning/payment/{invoice}](#get-lightningpaymentinvoice)
  - [GET /lightning/payments](#get-lightningpayments)
  - [Lightning Payment Example Workflow](#lightning-payment-example-workflow)
- [Error Responses](#error-responses)
- [Costs](#costs)
  - [Standard API Endpoints](#standard-api-endpoints)
  - [Lightning Network Payments](#lightning-network-payments)

## Authentication

Include your API key in the Authorization header:

```
Authorization: Bearer {your_api_key}
```

## POST /inference

Generate avatar videos with text-to-speech synthesis.

### Endpoints

- **Regular Request**: `POST https://api.avatartalk.ai/inference`
  - Returns JSON with video URLs
- **Streaming Request**: `POST https://api.avatartalk.ai/inference?stream=true`
  - Returns MP4 video data in real-time
- **Video Viewer**: `GET https://api.avatartalk.ai/inference/:id/video.html`
  - Displays video in browser

### Request Parameters

| Parameter | Type | Required | Description | Valid Values |
|-----------|------|----------|-------------|--------------|
| `text` | string | Yes | Text to be spoken by the avatar | Any text string |
| `avatar` | string | Yes | Avatar character to use | See [Avatar Options](#avatar-options) |
| `emotion` | string | Yes | Emotional expression for the avatar | `"happy"`, `"neutral"`, `"serious"` |
| `language` | string | No | Language for speech synthesis (defaults to `"en"`) | See [Language Options](#language-options) |
| `stream` | string | No | Enable streaming mode (query parameter) | `"true"` for streaming, omit for regular response |
| `delayed` | string/boolean | No | Enable delayed execution mode | `"true"` or `true` for delayed, omit for immediate execution |

#### Avatar Options

- `"japanese_man"` - Japanese Man
- `"old_european_woman"` - Elderly Woman
- `"european_woman"` - European Woman
- `"european_man"` - European Man
- `"african_man"` - African Man
- `"african_woman"` - African Woman
- `"japanese_woman"` - Japanese Woman
- `"iranian_man"` - Iranian Man
- `"mexican_man"` - Mexican Man
- `"mexican_woman"` - Mexican Woman
- `"colombian_woman"` - Colombian Woman
- `"old_japanese_man"` - Elderly Japanese Man
- `"arab_man"` - Arab Man
- `"arab_woman"` - Arab Woman

#### Language Options

- `"en"` - English
- `"es"` - Spanish
- `"fr"` - French
- `"de"` - German
- `"it"` - Italian
- `"pt"` - Portuguese
- `"pl"` - Polish
- `"tr"` - Turkish
- `"ru"` - Russian
- `"nl"` - Dutch
- `"cs"` - Czech
- `"ar"` - Arabic
- `"zh"` - Chinese
- `"ja"` - Japanese
- `"hu"` - Hungarian
- `"ko"` - Korean
- `"hi"` - Hindi

### Response Formats

#### Regular Request (JSON Response)

Returns JSON with inference details and video URLs:

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "success",
  "stream": false,
  "text": "Hello, this is a test message",
  "created_at": "2025-09-29T11:50:26.890669Z",
  "language": "en",
  "credits_consumed": 5,
  "avatar": "black_man",
  "emotion": "neutral",
  "file_size_bytes": 2048576,
  "inference_duration_ms": 3500,
  "video_duration_seconds": 4.2,
  "html_url": "https://api.avatartalk.ai/inference/123e4567-e89b-12d3-a456-426614174000/video.html",
  "mp4_url": "https://api.avatartalk.ai/inference/123e4567-e89b-12d3-a456-426614174000/video.mp4"
}
```

#### Delayed Request (JSON Response)

Returns JSON with pending status and trigger URLs:

```json
{
  "id": "456e7890-f12c-34d5-b678-901234567890",
  "status": "delayed",
  "stream": false,
  "text": "Hello! This video will be generated when accessed.",
  "created_at": "2025-09-29T11:50:26.890829Z",
  "language": "en",
  "credits_consumed": 0,
  "avatar": "black_man",
  "emotion": "neutral",
  "file_size_bytes": null,
  "inference_duration_ms": null,
  "video_duration_seconds": null,
  "html_url": "https://api.avatartalk.ai/inference/456e7890-f12c-34d5-b678-901234567890/video.html",
  "mp4_url": "https://api.avatartalk.ai/inference/456e7890-f12c-34d5-b678-901234567890/video.mp4"
}
```

**Note**: Both `mp4_url` and `html_url` are trigger URLs - accessing either will generate the video and consume credits.

#### Streaming Request (Binary Response)

Returns chunked MP4 video data as it's generated:

**Headers**:
```
Content-Type: video/mp4
Transfer-Encoding: chunked
Content-Disposition: attachment; filename="video.mp4"
Cache-Control: no-cache
```

**Body**: Raw MP4 video data streamed in real-time

## WebSocket /ws/infer

Real-time bidirectional streaming for avatar inference with support for audio and video input/output.

### Endpoint

```
wss://api.avatartalk.ai/ws/infer
```

### Query Parameters

| Parameter | Type | Required | Description | Valid Values |
|-----------|------|----------|-------------|--------------|
| `output_type` | string | Yes | Output format type | `"livekit"`, `"file"`, `"rtmp"` |
| `input_type` | string | Yes | Input format type | `"audio"`, `"text"` |
| `avatar` | string | Yes | Avatar character to use | See [Avatar Options](#avatar-options) |
| `stream_id` | string | No | Unique stream identifier (auto-generated if not provided) | UUID string |
| `emotion` | string | No | Emotional expression (defaults to `"neutral"`) | `"happy"`, `"neutral"`, `"serious"`, `"expressive"` |
| `language` | string | No | Language for speech synthesis | See [Language Options](#language-options) |
| `meeting_token` | string | No | Token for LiveKit meeting authentication | Valid LiveKit token |
| `as_agent` | boolean | No | Run as agent mode (defaults to `false`) | `true`, `false` |
| `increase_resolution` | boolean | No | Enable higher resolution output (defaults to `false`) | `true`, `false` |
| `rtmp_url` | string | No | RTMP streaming URL for output | Valid RTMP URL |

### Authentication

Use one of the following methods:

**Bearer Token (Standard)**:
```
Authorization: Bearer {your_api_key}
```

### Connection Flow

1. **Connect**: Establish WebSocket connection with required query parameters
2. **Authenticate**: Connection validates API key and authorization
3. **Stream Data**: Send and receive data based on `input_type` and `output_type`
4. **Close**: Connection terminates when streaming completes or on error

### Input/Output Types

#### Input Types

- **`text`**: Send text messages for the avatar to speak
- **`audio`**: Stream audio data for processing

#### Output Types

- **`audio`**: Receive audio output only
- **`video`**: Receive video with synchronized audio
- **`livekit`**: Stream output to LiveKit room

### WebSocket Messages

#### Sending Data (Client → Server)

Send binary audio data or JSON text messages based on `input_type`:

**Text Input**:
```json
{
  "text": "Hello, this is what the avatar should say"
}
```

**Audio Input**: Send raw binary audio data in chunks

#### Receiving Data (Server → Client)

Receive binary video/audio data or JSON status messages based on `output_type`.

### Error Handling

WebSocket will close with specific error codes:

| Code | Reason | Description |
|------|--------|-------------|
| 1008 | Invalid API key | The provided API key is invalid or missing |
| 1008 | Insufficient credits | Account does not have enough video time |
| 1008 | Authorization failed | Authorization validation failed |
| 1011 | Processing error | Internal server error during inference |

### Example Usage

```javascript
const ws = new WebSocket(
  'wss://api.avatartalk.ai/ws/infer?' +
  'output_type=file&' +
  'input_type=text&' +
  'avatar=european_woman&' +
  'emotion=happy&' +
  'language=en'
);

ws.addEventListener('open', () => {
  // Send text for the avatar to speak
  ws.send(JSON.stringify({
    text: "Hello! Welcome to AvatarTalk."
  }));
});

ws.addEventListener('message', (event) => {
  // Receive video/audio data
  const videoData = event.data;
  // Process received data
});

ws.addEventListener('close', (event) => {
  console.log('Connection closed:', event.code, event.reason);
});
```

## WebSocket /ws/continuous

Persistent, low-latency video streaming with smooth transitions between silence and speech. Ideal for real-time conversational applications with automatic turn-taking.

### Endpoint

```
wss://api.avatartalk.ai/ws/continuous
```

### Query Parameters

| Parameter | Type | Required | Description | Valid Values |
|-----------|------|----------|-------------|--------------|
| `avatar` | string | Yes | Avatar character to use | Currently only available for `"mexican_woman"`. Other avatars can be requested. See [Avatar Options](#avatar-options) |
| `expression` | string | No | Initial expression (defaults to `"neutral"`) | `"happy"`, `"neutral"`, `"serious"` |
| `language` | string | No | Language code (defaults to `"en"`) | Currently only `"en"` supported |

**Note**: .

### Authentication

Authentication methods:

**Bearer Token**:
```
Authorization: Bearer {your_api_key}
```

### Protocol

The continuous streaming endpoint uses a unified WebSocket for both control messages and video data:

- **Client → Server (Text frames)**: JSON control messages
- **Server → Client (Text frames)**: JSON responses
- **Server → Client (Binary frames)**: MP4 video chunks

### Message Types

| Type | Direction | Description |
|------|-----------|-------------|
| `session_start` | Client → Server | Initialize streaming session |
| `text_input` | Client → Server | Send text to synthesize |
| `text_append` | Client → Server | Append text to ongoing generation |
| `turn_start` | Client → Server | Trigger end-of-turn pregen segment |
| `session_ready` | Server → Client | Session successfully started |
| `state_change` | Server → Client | State machine transition |
| `ready_to_listen` | Server → Client | Client can enable microphone |

---

### Message Format

All messages use JSON envelope:
```json
{"type": "<message_type>", "data": {...}}
```

---

### Client → Server Messages

#### session_start

Initialize streaming session. **Must be sent first.**

```json
{
  "type": "session_start",
  "data": {
    "avatar_name": "mexican_woman",
    "expression": "neutral",
    "language": "en",
    "expressive_mode": false,
    "target_buffer_ms": 2000,
    "min_buffer_ms": 500,
    "max_buffer_ms": 5000
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `avatar_name` | string | **required** | Avatar identifier |
| `expression` | string | **required** | `happy`, `neutral`, `serious` |
| `language` | string | `"en"` | Language code |
| `expressive_mode` | bool | `false` | Dynamically change expressions|
| `target_buffer_ms` | int | `2000` | Target buffer level |
| `min_buffer_ms` | int | `500` | Minimum buffer |
| `max_buffer_ms` | int | `5000` | Maximum buffer |

---

#### text_input

Send text for speech generation.

```json
{
  "type": "text_input",
  "data": {
    "text": "Hello, how are you?",
    "expression": "happy",
    "mode": "dynamic_only"
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | string | **required** | Text to synthesize |
| `expression` | string | current | Change expression |
| `mode` | string | `"full"` | `"full"` or `"dynamic_only"` |

---

#### text_append

Append to ongoing generation (streaming LLM).

```json
{
  "type": "text_append",
  "data": {"text": "Additional sentence."}
}
```

---

#### text_stream_done

Signal text stream complete.

```json
{"type": "text_stream_done", "data": {}}
```

---

#### turn_start

Trigger End-of-Turn pregenerated segment.

```json
{
  "type": "turn_start",
  "data": {"expression": "neutral"}
}
```

---

#### buffer_status

Report client buffer level.

```json
{
  "type": "buffer_status",
  "data": {"buffered_ms": 1500, "playback_position": 10.5}
}
```

---

#### session_end

End session gracefully.

```json
{"type": "session_end", "data": {}}
```

---

### Server → Client Messages

#### session_ready

Session initialized.

```json
{
  "type": "session_ready",
  "data": {"session_id": "abc123", "initial_buffer_ms": 2000}
}
```

---

#### state_change

State transition.

```json
{
  "type": "state_change",
  "data": {"from": "silence", "to": "dynamic_speech", "timestamp": 1699123456.789}
}
```

**States:** `initial`, `silence`, `silence_to_pregen`, `pregen_video`, `pregen_to_dynamic`, `dynamic_speech`, `dynamic_to_silence`, `terminated`

---

#### ready_to_listen

Client can enable microphone.

```json
{"type": "ready_to_listen", "data": {"timestamp": 1699123456.789}}
```

---

#### text_queued / text_appended / text_stream_completed

Acknowledgments.

```json
{"type": "text_queued", "data": {"session_id": "abc123", "text_length": 45}}
{"type": "text_appended", "data": {"session_id": "abc123", "text_length": 25}}
{"type": "text_stream_completed", "data": {"session_id": "abc123"}}
```

---

#### buffer_warning

Buffer critical.

```json
{"type": "buffer_warning", "data": {"level": "critical", "buffer_ms": 200}}
```

---

#### billing_error

User out of credits.

```json
{
  "type": "billing_error",
  "data": {"session_id": "abc123", "message": "Insufficient credits", "error_code": "insufficient_credits"}
}
```

| Error Code | Description |
|------------|-------------|
| `insufficient_credits` | No credits remaining |
| `session_not_found` | Billing session not found |
| `billing_error` | Other billing error |

---

#### error

General error.

```json
{"type": "error", "data": {"message": "Session not found", "session_id": "abc123"}}
```

---

### Binary Frames

Binary WebSocket frames contain **fMP4 (fragmented MP4)** video chunks.

| Property | Value |
|----------|-------|
| Codec | H.264 |
| Container | fMP4 |
| Frame rate | 25 FPS |
| Resolution | 512×512 |
| Audio | AAC @ 48kHz |

---

## LiveKit Session Management

Manage real-time avatar sessions using LiveKit for video conferencing and interactive applications.

### Create LiveKit Session

Create a new LiveKit session with an avatar agent.

#### Endpoint

```
POST https://api.avatartalk.ai/livekit/create-session
```

#### Request Body

```json
{
  "room_name": "my-meeting-room",
  "room_token": "participant_token",
  "listener_token": "listener_token",
  "livekit_url": "wss://livekit.example.com",
  "avatar": "european_woman",
  "emotion": "neutral"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `room_name` | string | Yes | LiveKit room identifier |
| `room_token` | string | Yes | LiveKit participant token for the avatar |
| `listener_token` | string | Yes | LiveKit listener token for monitoring |
| `livekit_url` | string | Yes | WebSocket URL of LiveKit server |
| `avatar` | string | Yes | Avatar character to use (see [Avatar Options](#avatar-options)) |
| `emotion` | string | Yes | Avatar emotional expression (`"happy"`, `"neutral"`, `"serious"`, `"expressive"`) |

**Note**: If `emotion` is set to `"expressive"`, it will be automatically converted to `"neutral"` for the avatar.

#### Response

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Unique identifier for the session task (use this to delete the session) |

#### Example Request

```bash
curl -X POST https://api.avatartalk.ai/livekit/create-session \
  -H "Authorization: Bearer your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "room_name": "demo-room",
    "room_token": "eyJhbGc...",
    "listener_token": "eyJhbGc...",
    "livekit_url": "wss://my-livekit.com",
    "avatar": "japanese_woman",
    "emotion": "happy"
  }'
```

### Delete LiveKit Session

Terminate an active LiveKit session.

#### Endpoint

```
DELETE https://api.avatartalk.ai/livekit/delete-session/{task_id}
```

#### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_id` | string | Yes | The task ID returned from session creation |

#### Response

**Success (200)**:
```json
{
  "status": "Task 550e8400-e29b-41d4-a716-446655440000 deleted successfully"
}
```

**Error (404)**:
```json
{
  "detail": "Task 550e8400-e29b-41d4-a716-446655440000 not found"
}
```

#### Example Request

```bash
curl -X DELETE https://api.avatartalk.ai/livekit/delete-session/550e8400-e29b-41d4-a716-446655440000 \
  -H "Authorization: Bearer your_api_key"
```

## Error Responses

All endpoints return standardized JSON error responses:

### 400 Bad Request - Invalid Parameters

```json
{
  "status": "error",
  "error_code": "INVALID_PARAMETERS",
  "message": "Request parameters are invalid",
  "details": {}
}
```

### 401 Unauthorized - Invalid API Key

```json
{
  "status": "error",
  "error_code": "INVALID_API_KEY",
  "message": "Invalid or missing API key"
}
```

### 403 Forbidden - Insufficient Credits

```json
{
  "status": "error",
  "error_code": "INSUFFICIENT_CREDITS",
  "message": "Insufficient video time to process request"
}
```

### 404 Not Found

```json
{
  "detail": "Resource not found"
}
```

### 500 Internal Server Error - Processing Failed

```json
{
  "status": "error",
  "error_code": "INFERENCE_FAILED",
  "message": "Inference processing failed"
}
```

## Lightning Network Payment Endpoints

Pay for avatar video generation using Bitcoin Lightning Network payments. This payment flow uses BOLT11 invoices.

### Payment Flow Overview

1. **Request Video**: Submit text or audio to `/lightning/request-video/text` or `/lightning/request-video/audio`
2. **Receive Invoice**: Get a BOLT11 invoice with the cost and duration estimate
3. **Pay Invoice**: Pay the BOLT11 invoice using your Lightning wallet
4. **Generate Video**: Call `/lightning/generate-video` with the invoice to retrieve your video

### POST /lightning/request-video/text

Create a video request from text and receive a Lightning invoice for payment.

#### Endpoint

```
POST https://api.avatartalk.ai/lightning/request-video/text
```

#### Request Body

```json
{
  "text": "Hello! This is the text that will be spoken by the avatar."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | Yes | Text content to be converted to speech |

#### Response

```json
{
  "duration": 4.5,
  "bolt11_invoice": "lnbc450n1p3...",
  "amount": 450
}
```

| Field | Type | Description |
|-------|------|-------------|
| `duration` | number | Estimated video duration in seconds |
| `bolt11_invoice` | string | Lightning Network BOLT11 invoice string |
| `amount` | integer | Payment amount in satoshis |

#### Example Request

```bash
curl -X POST https://api.avatartalk.ai/lightning/request-video/text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Welcome to AvatarTalk! This is a demonstration of our text-to-speech technology."
  }'
```

### POST /lightning/request-video/audio

Create a video request from an audio file and receive a Lightning invoice for payment.

#### Endpoint

```
POST https://api.avatartalk.ai/lightning/request-video/audio
```

#### Request Parameters

Multipart form data with an audio file:

| Field | Type | Required | Description | Format |
|-------|------|----------|-------------|--------|
| `audio` | file | Yes | Audio file to be processed | WAV format, 16kHz, mono, 16-bit |

#### Audio File Requirements

- **Format**: WAV (`.wav`)
- **Sample Rate**: 16kHz
- **Channels**: Mono
- **Bit Depth**: 16-bit
- **Minimum Size**: 44 bytes (valid WAV header)

#### Response

```json
{
  "duration": 8.2,
  "bolt11_invoice": "lnbc820n1p3...",
  "amount": 820
}
```

| Field | Type | Description |
|-------|------|-------------|
| `duration` | number | Actual audio duration in seconds |
| `bolt11_invoice` | string | Lightning Network BOLT11 invoice string |
| `amount` | integer | Payment amount in satoshis |

#### Error Responses

**400 Bad Request - Missing File**:
```json
{
  "detail": "Audio file is required"
}
```

**400 Bad Request - Invalid Format**:
```json
{
  "detail": "Only WAV files are supported. Please upload a .wav file."
}
```

**400 Bad Request - Invalid WAV**:
```json
{
  "detail": "Invalid WAV file: too small"
}
```

#### Example Request

```bash
curl -X POST https://api.avatartalk.ai/lightning/request-video/audio \
  -F "audio=@speech.wav"
```

### POST /lightning/generate-video

Generate and retrieve the video after paying the Lightning invoice.

#### Endpoint

```
POST https://api.avatartalk.ai/lightning/generate-video
```

#### Request Body

```json
{
  "bolt11_invoice": "lnbc450n1p3...",
  "avatar": "european_woman",
  "emotion": "happy",
  "language": "en"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `bolt11_invoice` | string | Yes | The BOLT11 invoice from the request step (must be paid) |
| `avatar` | string | Yes | Avatar character to use (see [Avatar Options](#avatar-options)) |
| `emotion` | string | Yes | Avatar emotional expression: `"happy"`, `"neutral"`, `"serious"`, `"expressive"` |
| `language` | string | No | Language code for speech synthesis (see [Language Options](#language-options)) |

**Note**: If `emotion` is set to `"expressive"`, it will be automatically converted to `"neutral"` for processing.

#### Response

Returns a streaming MP4 video file:

**Headers**:
```
Content-Type: video/mp4
Cache-Control: no-cache
```

**Body**: Binary MP4 video data (streamed)

#### Error Responses

**400 Bad Request - Invoice Not Paid**:
```json
{
  "detail": "Invoice not paid in time."
}
```

**404 Not Found - Invoice Not Found**:
```json
{
  "detail": "Invoice lnbc450n1p... not found."
}
```

#### Example Request

```bash
curl -X POST https://api.avatartalk.ai/lightning/generate-video \
  -H "Content-Type: application/json" \
  -d '{
    "bolt11_invoice": "lnbc450n1p3...",
    "avatar": "japanese_woman",
    "emotion": "happy",
    "language": "en"
  }' \
  --output video.mp4
```

### GET /lightning/payment/{invoice}

Check the payment status of a specific Lightning invoice.

#### Endpoint

```
GET https://api.avatartalk.ai/lightning/payment/{invoice}
```

#### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `invoice` | string | Yes | The BOLT11 invoice string |

#### Response

Returns payment details:

```json
{
  "invoice": "lnbc450n1p3...",
  "amount_sat": 450,
  "amount_usd": 0.15,
  "status": "paid",
  "created_at": "2025-09-29T12:00:00Z",
  "paid_at": "2025-09-29T12:01:30Z"
}
```

#### Error Responses

**404 Not Found**:
```json
{
  "detail": "Payment not found"
}
```

#### Example Request

```bash
curl -X GET https://api.avatartalk.ai/lightning/payment/lnbc450n1p3... \
  -H "Authorization: Bearer your_api_key"
```

### GET /lightning/payments

List all Lightning payments (requires authentication).

#### Endpoint

```
GET https://api.avatartalk.ai/lightning/payments
```

#### Authentication

Requires API key:
```
Authorization: Bearer {your_api_key}
```

#### Response

Returns an array of all payment records:

```json
[
  {
    "id": 1,
    "invoice": "lnbc450n1p3...",
    "amount_sat": 450,
    "amount_usd": 0.15,
    "status": "paid",
    "created_at": "2025-09-29T12:00:00Z",
    "paid_at": "2025-09-29T12:01:30Z"
  },
  {
    "id": 2,
    "invoice": "lnbc820n1p3...",
    "amount_sat": 820,
    "amount_usd": 0.28,
    "status": "pending",
    "created_at": "2025-09-29T12:05:00Z",
    "paid_at": null
  }
]
```

#### Example Request

```bash
curl -X GET https://api.avatartalk.ai/lightning/payments \
  -H "Authorization: Bearer your_api_key"
```

### Lightning Payment Example Workflow

Here's a complete example of the Lightning payment workflow:

```bash
# Step 1: Request a video from text
RESPONSE=$(curl -X POST https://api.avatartalk.ai/lightning/request-video/text \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from AvatarTalk!"}')

# Extract invoice and amount
INVOICE=$(echo $RESPONSE | jq -r '.bolt11_invoice')
AMOUNT=$(echo $RESPONSE | jq -r '.amount')
echo "Invoice: $INVOICE"
echo "Amount: $AMOUNT sats"

# Step 2: Pay the invoice using your Lightning wallet
# (Use your preferred Lightning wallet or CLI tool)
# lightning-cli pay $INVOICE

# Step 3: Check payment status (optional)
curl -X GET https://api.avatartalk.ai/lightning/payment/$INVOICE

# Step 4: Generate and download the video
curl -X POST https://api.avatartalk.ai/lightning/generate-video \
  -H "Content-Type: application/json" \
  -d "{
    \"bolt11_invoice\": \"$INVOICE\",
    \"avatar\": \"european_woman\",
    \"emotion\": \"happy\",
    \"language\": \"en\"
  }" \
  --output my_video.mp4
```

## Costs

### Standard API Endpoints

Each successful inference consumes video time from your account:

- **1 second of generated video = 1 second of video time**

Video time is consumed when:
- Regular `/api/inference` request completes successfully
- Delayed request URLs (`mp4_url` or `html_url`) are accessed
- WebSocket streaming generates video output
- LiveKit sessions are active

Check your account balance through the AvatarTalk dashboard to monitor remaining video time.

### Lightning Network Payments

When using Lightning Network endpoints (`/lightning/*`), payment is calculated based on the estimated or actual duration of the generated video:

- **Cost per second**: Determined by the current market rate (returned in the invoice)
- **Payment method**: Bitcoin Lightning Network (BOLT11 invoices)
- **Instant settlement**: Videos are generated immediately after invoice payment is confirmed

The exact cost in satoshis and USD is provided in the response when you request a video. Payment must be completed before the video can be generated.
