import express from 'express';
import nunjucks from 'nunjucks';
import multer from 'multer';
import crypto from 'node:crypto';
import { Readable } from 'node:stream';

import { settings } from './config.js';
import { chatComplete, transcribeAudioBuffer } from './openai_client.js';
import { inference } from './avatartalk_client.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();

// Templates
const TEMPLATES_DIR = path.resolve(__dirname, '..', 'templates');
nunjucks.configure(TEMPLATES_DIR, {
  autoescape: true,
  express: app,
});

// Body parsers
app.use(express.json({ limit: '4mb' }));
app.use(express.urlencoded({ extended: true }));

// Multer in-memory storage for audio uploads
const upload = multer({ storage: multer.memoryStorage() });

// In-memory pending streams with TTL
const pendingStreams = new Map(); // id -> { text, avatar, emotion, language, expiresAt }
const STREAM_TTL_MS = 10 * 60 * 1000; // 10 minutes

// Janitor to clean expired stream ids
setInterval(() => {
  const now = Date.now();
  for (const [id, info] of pendingStreams.entries()) {
    if (info.expiresAt && info.expiresAt < now) {
      pendingStreams.delete(id);
    }
  }
}, 60 * 1000);

app.get('/healthz', (_req, res) => {
  res.json({ status: 'ok' });
});

app.get('/', (req, res) => {
  res.render('index.html', {
    request: req, // for compatibility (not used by nunjucks)
    model: settings.openai_model,
    avatar: settings.avatar,
    emotion: settings.emotion,
    language: settings.language,
    delayed: settings.delayed,
  });
});

app.post('/chat', async (req, res) => {
  try {
    const payload = req.body || {};
    const userText = payload.user_text;
    if (!userText) {
      return res.status(400).json({ error: 'user_text is required' });
    }

    const history = Array.isArray(payload.history) ? payload.history : [];
    const messages = [];
    for (const msg of history) {
      const role = msg?.role;
      const content = msg?.content;
      if ((role === 'system' || role === 'user' || role === 'assistant') && content) {
        messages.push({ role, content });
      }
    }
    messages.push({ role: 'user', content: userText });

    const assistantText = await chatComplete(messages);

    const avatar = payload.avatar || undefined;
    const emotion = payload.emotion || undefined;
    const language = payload.language || undefined;

    let atJson = {};
    try {
      atJson = await inference(assistantText, { avatar, emotion, language });
    } catch (e) {
      atJson = { status: 'error', message: String(e?.message || e) };
    }

    res.json({ assistant_text: assistantText, inference: atJson });
  } catch (e) {
    res.status(500).json({ error: String(e?.message || e) });
  }
});

app.post('/voice', upload.single('audio'), async (req, res) => {
  try {
    const file = req.file;
    if (!file || !file.buffer || !file.buffer.length) {
      return res.status(400).json({ error: 'empty audio' });
    }

    // Parse optional history (stringified JSON)
    let msgs = [];
    const historyStr = req.body?.history;
    if (historyStr) {
      try {
        const parsed = JSON.parse(historyStr);
        for (const msg of parsed || []) {
          if ((msg?.role === 'system' || msg?.role === 'user' || msg?.role === 'assistant') && msg?.content) {
            msgs.push({ role: msg.role, content: msg.content });
          }
        }
      } catch {}
    }

    const userText = await transcribeAudioBuffer(file.buffer, file.originalname || 'audio.webm');
    if (!userText) {
      return res.status(500).json({ error: 'transcription failed' });
    }

    msgs.push({ role: 'user', content: userText });
    const assistantText = await chatComplete(msgs);

    let atJson = {};
    try {
      atJson = await inference(assistantText);
    } catch (e) {
      atJson = { status: 'error', message: String(e?.message || e) };
    }

    res.json({ user_text: userText, assistant_text: assistantText, inference: atJson });
  } catch (e) {
    res.status(500).json({ error: String(e?.message || e) });
  }
});

app.post('/transcribe', upload.single('audio'), async (req, res) => {
  try {
    const file = req.file;
    if (!file || !file.buffer || !file.buffer.length) {
      return res.status(400).json({ error: 'empty audio' });
    }
    const text = await transcribeAudioBuffer(file.buffer, file.originalname || 'audio.webm');
    res.json({ user_text: text });
  } catch (e) {
    res.status(500).json({ error: String(e?.message || e) });
  }
});

app.post('/chat_stream', async (req, res) => {
  try {
    const payload = req.body || {};
    const userText = payload.user_text;
    if (!userText) {
      return res.status(400).json({ error: 'user_text is required' });
    }

    const history = Array.isArray(payload.history) ? payload.history : [];
    const messages = [];
    for (const msg of history) {
      const role = msg?.role;
      const content = msg?.content;
      if ((role === 'system' || role === 'user' || role === 'assistant') && content) {
        messages.push({ role, content });
      }
    }
    messages.push({ role: 'user', content: userText });

    const assistantText = await chatComplete(messages);

    const avatar = payload.avatar || settings.avatar;
    const emotion = payload.emotion || settings.emotion;
    const language = payload.language || settings.language;

    const sid = crypto.randomUUID();
    pendingStreams.set(sid, {
      text: assistantText,
      avatar,
      emotion,
      language,
      expiresAt: Date.now() + STREAM_TTL_MS,
    });
    res.json({ assistant_text: assistantText, stream_id: sid, stream_url: `/stream/${sid}.mp4` });
  } catch (e) {
    res.status(500).json({ error: String(e?.message || e) });
  }
});

app.get('/stream/:sid.mp4', async (req, res) => {
  const sid = req.params.sid;
  const info = pendingStreams.get(sid);
  if (!info) {
    return res.status(404).json({ error: 'invalid or expired stream id' });
  }
  // Pop the entry (one-time use) and check TTL
  pendingStreams.delete(sid);
  if (info.expiresAt && info.expiresAt < Date.now()) {
    return res.status(404).json({ error: 'invalid or expired stream id' });
  }

  const payload = {
    text: info.text,
    avatar: info.avatar || settings.avatar,
    emotion: info.emotion || settings.emotion,
    language: info.language || settings.language,
  };
  const base = settings.avatartalk_base_url.replace(/\/$/, '');
  const url = `${base}/inference?stream=true`;

  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${settings.avatartalk_api_key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!r.ok || !r.body) {
      const text = await r.text().catch(() => '');
      return res.status(r.status || 502).send(text || 'stream init failed');
    }

    res.setHeader('Content-Type', 'video/mp4');
    res.setHeader('Content-Disposition', 'inline; filename=stream.mp4');
    res.setHeader('Cache-Control', 'no-cache');

    // Pipe the web ReadableStream to Node's res
    Readable.fromWeb(r.body).pipe(res);
  } catch (e) {
    res.status(500).json({ error: String(e?.message || e) });
  }
});

app.listen(settings.port, settings.host, () => {
  // eslint-disable-next-line no-console
  console.log(`AvatarTalk Simple WebChat listening on http://${settings.host}:${settings.port}`);
});

