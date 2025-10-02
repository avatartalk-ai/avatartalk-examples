# AvatarTalk API Documentation

## Base URL

`https://api.avatartalk.ai`

## Table of Contents

- [Base URL](#base-url)
- [Authentication](#authentication)
- [POST /inference](#post-inference)
- [WebSocket /ws/infer](#websocket-wsinfer)
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

## Common parameters

Options used throughout the API:

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

#### Emotion options

- `"happy"`
- `"neutral"`
- `"serious"`

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
| `emotion` | string | Yes | Emotional expression for the avatar | See [Emotion Options](#emotion-options) |
| `language` | string | No | Language for speech synthesis (defaults to `"en"`) | See [Language Options](#language-options) |
| `stream` | string | No | Enable streaming mode (query parameter) | `"true"` for streaming, omit for regular response |
| `delayed` | string/boolean | No | Enable delayed execution mode | `"true"` or `true` for delayed, omit for immediate execution |

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
  "avatar": "african_man",
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
  "avatar": "african_man",
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
wss://avatartalk.ai/ws/infer
```

### Query Parameters

| Parameter | Type | Required | Description | Valid Values |
|-----------|------|----------|-------------|--------------|
| `output_type` | string | Yes | Output format type | `"livekit"`, `"file"`, `"rtmp"` |
| `input_type` | string | Yes | Input format type | `"audio"`, `"text"` |
| `avatar` | string | Yes | Avatar character to use | See [Avatar Options](#avatar-options) |
| `stream_id` | string | No | Unique stream identifier (auto-generated if not provided) | UUID string |
| `emotion` | string | No | Emotional expression (defaults to `"neutral"`) | See [Emotion Options](#emotion-options) |
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

| Field | Type | Required | Description | Valid Values |
|-------|------|----------|-------------|--------------|
| `room_name` | string | Yes | LiveKit room identifier | Valid LiveKit room name |
| `room_token` | string | Yes | LiveKit participant token for the avatar | Valid LiveKit room JWT token |
| `listener_token` | string | Yes | LiveKit listener token for monitoring | Valid LiveKit room JWT token |
| `livekit_url` | string | Yes | WebSocket URL of LiveKit server | `wss://livekit.example.com` |
| `avatar` | string | Yes | Avatar character to use | See [Avatar Options](#avatar-options) |
| `emotion` | string | Yes | Avatar emotional expression | See [Emotion Options](#emotion-options) |

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

<br>

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

| Field | Type | Required | Description | Valid Values |
|-------|------|----------|-------------|--------------|
| `bolt11_invoice` | string | Yes | The BOLT11 invoice from the request step (must be paid) | Valid BOLT11 invoice |
| `avatar` | string | Yes | Avatar character to use | See [Avatar Options](#avatar-options) |
| `emotion` | string | Yes | Avatar emotional expression | See [Emotion Options](#emotion-options) |
| `language` | string | No | Language code for speech synthesis | See [Language Options](#language-options) |

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
