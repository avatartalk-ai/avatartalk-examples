import express from 'express';
import nunjucks from 'nunjucks';
import multer from 'multer';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import crypto from 'node:crypto';
import { Readable } from 'node:stream';
import { URL } from 'node:url';

import { settings } from './config.js';
import { chatComplete, transcribeAudioBuffer } from './openai_client.js';
import { sendTextToAvatarViaWS } from './avatartalk_ws.js';

import { AccessToken, RoomServiceClient } from 'livekit-server-sdk';
import WebSocket, { WebSocketServer } from 'ws';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();

// Templates
const TEMPLATES_DIR = path.resolve(__dirname, '..', 'templates');
nunjucks.configure(TEMPLATES_DIR, { autoescape: true, express: app });

// Body parsers
app.use(express.json({ limit: '4mb' }));
app.use(express.urlencoded({ extended: true }));

// Multer in-memory storage for audio uploads
const upload = multer({ storage: multer.memoryStorage() });

// In-memory session store (ephemeral)
const sessions = new Map(); // session_id -> { room, avatar_token, created_at, expires_at }
const SESSION_TTL_MS = 6 * 60 * 60 * 1000;

function nowMs() { return Date.now(); }

function cleanupSessions() {
  const now = nowMs();
  for (const [sid, s] of sessions.entries()) {
    if (s.expires_at && s.expires_at < now) sessions.delete(sid);
  }
}
setInterval(cleanupSessions, 60_000).unref?.();

function mintLivekitToken({ identity, room }) {
  if (!settings.livekit_api_key || !settings.livekit_api_secret) {
    throw new Error('LIVEKIT_API_KEY/SECRET not set');
  }
  const at = new AccessToken(settings.livekit_api_key, settings.livekit_api_secret, {
    identity,
    ttl: settings.livekit_token_ttl_seconds,
  });
  at.addGrant({ roomJoin: true, room });
  return at.toJwt();
}

app.get('/healthz', (_req, res) => {
  res.json({ status: 'ok' });
});

app.get('/', (req, res) => {
  res.render('index.html', {
    request: req,
    model: settings.openai_model,
    avatar: settings.avatar,
    emotion: settings.emotion,
    language: settings.language,
    livekit_url: settings.livekit_url || '',
  });
});

app.post('/session', async (req, res) => {
  try {
    if (!settings.livekit_url) {
      return res.status(500).json({ error: 'LIVEKIT_URL is not set' });
    }
    const sessionId = crypto.randomUUID();
    const roomName = `lk-${sessionId.slice(0, 8)}`;
    const userIdentity = `user-${sessionId.slice(0, 8)}`;
    const avatarIdentity = `avatar-${sessionId.slice(0, 8)}`;

    // Optionally create the room up-front; ignore errors
    try {
      if (settings.livekit_api_key && settings.livekit_api_secret) {
        const base = settings.livekit_url.replace(/^wss?:\/\//, (m) => m === 'wss://' ? 'https://' : 'http://');
        const svc = new RoomServiceClient(base, settings.livekit_api_key, settings.livekit_api_secret);
        await svc.createRoom({ name: roomName }).catch(() => { });
      }
    } catch { }

    const userToken = await mintLivekitToken({
      identity: userIdentity,
      room: roomName,
    });
    const avatarToken = await mintLivekitToken({
      identity: avatarIdentity,
      room: roomName,
    });

    sessions.set(sessionId, {
      room: roomName,
      avatar_token: avatarToken,
      created_at: nowMs(),
      expires_at: nowMs() + SESSION_TTL_MS,
    });

    res.json({
      session_id: sessionId,
      room_name: roomName,
      livekit_url: settings.livekit_url,
      token: userToken,
    });
  } catch (e) {
    res.status(500).json({ error: String(e?.message || e) });
  }
});

app.post('/chat', async (req, res) => {
  try {
    cleanupSessions();
    const payload = req.body || {};
    const userText = payload.user_text;
    const sessionId = payload.session_id;
    const history = Array.isArray(payload.history) ? payload.history : [];
    if (!userText) return res.status(400).json({ error: 'user_text is required' });
    if (!sessionId || !sessions.has(sessionId)) return res.status(400).json({ error: 'invalid session_id' });

    const messages = [];
    for (const msg of history) {
      const role = msg?.role, content = msg?.content;
      if ((role === 'system' || role === 'user' || role === 'assistant') && content) messages.push({ role, content });
    }
    messages.push({ role: 'user', content: userText });

    const assistantText = await chatComplete(messages);

    const avatar = payload.avatar || settings.avatar;
    const emotion = payload.emotion || settings.emotion;
    const language = payload.language || settings.language;
    const increaseResolution = Boolean(payload.increase_resolution);

    if (!settings.avatartalk_api_key) return res.status(500).json({ error: 'AVATARTALK_API_KEY is not set' });

    const meetingToken = sessions.get(sessionId).avatar_token;
    try {
      await sendTextToAvatarViaWS({
        meetingToken,
        text: assistantText,
        avatar,
        emotion,
        language,
        increaseResolution,
      });
      res.json({ assistant_text: assistantText });
    } catch (e) {
      res.status(500).json({ assistant_text: assistantText, warning: `avatar stream error: ${String(e?.message || e)}` });
    }
  } catch (e) {
    res.status(500).json({ error: String(e?.message || e) });
  }
});

app.post('/voice', upload.single('audio'), async (req, res) => {
  try {
    cleanupSessions();
    const sessionId = req.body?.session_id;
    if (!sessionId || !sessions.has(sessionId)) return res.status(400).json({ error: 'invalid session_id' });

    const file = req.file;
    if (!file || !file.buffer?.length) return res.status(400).json({ error: 'empty audio' });

    let msgs = [];
    const historyStr = req.body?.history;
    if (historyStr) {
      try {
        const parsed = JSON.parse(historyStr);
        for (const msg of parsed || []) {
          const role = msg?.role, content = msg?.content;
          if ((role === 'system' || role === 'user' || role === 'assistant') && content) msgs.push({ role, content });
        }
      } catch { }
    }
    const userText = await transcribeAudioBuffer(file.buffer, file.originalname || 'audio.webm');
    if (!userText) return res.status(500).json({ error: 'transcription failed' });
    msgs.push({ role: 'user', content: userText });
    const assistantText = await chatComplete(msgs);

    const avatar = req.body?.avatar || settings.avatar;
    const emotion = req.body?.emotion || settings.emotion;
    const language = req.body?.language || settings.language;
    const increaseResolution = String(req.body?.increase_resolution || '').toLowerCase() === 'true'
      || String(req.body?.increase_resolution || '').toLowerCase() === '1'
      || String(req.body?.increase_resolution || '').toLowerCase() === 'yes'
      || String(req.body?.increase_resolution || '').toLowerCase() === 'on';

    if (!settings.avatartalk_api_key) return res.status(500).json({ error: 'AVATARTALK_API_KEY is not set' });
    const meetingToken = sessions.get(sessionId).avatar_token;
    try {
      await sendTextToAvatarViaWS({
        meetingToken,
        text: assistantText,
        avatar,
        emotion,
        language,
        increaseResolution,
      });
      res.json({ user_text: userText, assistant_text: assistantText });
    } catch (e) {
      res.json({ user_text: userText, assistant_text: assistantText, warning: `avatar stream error: ${String(e?.message || e)}` });
    }
  } catch (e) {
    res.status(500).json({ error: String(e?.message || e) });
  }
});

app.post('/transcribe', upload.single('audio'), async (req, res) => {
  try {
    const file = req.file;
    if (!file || !file.buffer?.length) return res.status(400).json({ error: 'empty audio' });
    const text = await transcribeAudioBuffer(file.buffer, file.originalname || 'audio.webm');
    res.json({ user_text: text });
  } catch (e) {
    res.status(500).json({ error: String(e?.message || e) });
  }
});

// Start HTTP server and attach WS bridge for /ws/audio
const server = app.listen(settings.port, settings.host, () => {
  // eslint-disable-next-line no-console
  console.log(`AvatarTalk LiveKit WebChat listening on http://${settings.host}:${settings.port}`);
});

const wss = new WebSocketServer({ noServer: true });

server.on('upgrade', (req, socket, head) => {
  try {
    const { pathname } = new URL(req.url, `http://${req.headers.host}`);
    if (pathname === '/ws/audio') {
      wss.handleUpgrade(req, socket, head, (ws) => {
        wss.emit('connection', ws, req);
      });
    } else {
      socket.destroy();
    }
  } catch {
    socket.destroy();
  }
});

wss.on('connection', async (clientWs, req) => {
  // Relay browser binary frames to AvatarTalk /ws/infer with input_type=audio
  const url = new URL(req.url, `http://${req.headers.host}`);
  const sessionId = url.searchParams.get('session_id');
  const avatar = url.searchParams.get('avatar') || settings.avatar;
  const emotion = url.searchParams.get('emotion') || settings.emotion;
  const language = url.searchParams.get('language') || settings.language;
  const incStr = (url.searchParams.get('increase_resolution') || '').toLowerCase();
  const incRes = incStr === '1' || incStr === 'true' || incStr === 'yes' || incStr === 'on';

  try {
    cleanupSessions();
    if (!sessionId || !sessions.has(sessionId)) {
      clientWs.close(4000);
      return;
    }
    if (!settings.avatartalk_api_key) {
      clientWs.close(4001);
      return;
    }
    const meetingToken = sessions.get(sessionId).avatar_token;
    const base = settings.avatartalk_ws_base_url.replace(/\/$/, '');
    const qs = new URLSearchParams({
      output_type: 'livekit',
      input_type: 'audio',
      avatar,
      emotion,
      language,
      meeting_token: meetingToken,
      increase_resolution: incRes ? 'true' : 'false',
    });
    const upstreamUrl = `${base}/ws/infer?${qs.toString()}`;
    const upstream = new WebSocket(upstreamUrl, {
      headers: { Authorization: `Bearer ${settings.avatartalk_api_key}` },
      perMessageDeflate: false,
      maxPayload: 0, // no limit
    });

    upstream.on('open', () => {
      // Forward client binary frames
      clientWs.on('message', (data, isBinary) => {
        try { upstream.send(data, { binary: isBinary }); } catch { }
      });
    });

    // Optionally read upstream messages to keep connection healthy
    upstream.on('message', () => { /* ignore status frames */ });

    const closeBoth = () => { try { upstream.close(); } catch { } try { clientWs.close(); } catch { } };
    upstream.on('error', closeBoth);
    clientWs.on('error', closeBoth);
    upstream.on('close', () => { try { clientWs.close(); } catch { } });
    clientWs.on('close', () => { try { upstream.close(); } catch { } });
  } catch {
    try { clientWs.close(1011); } catch { }
  }
});
