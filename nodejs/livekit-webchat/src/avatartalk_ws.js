import WebSocket from 'ws';
import { settings } from './config.js';

export async function sendTextToAvatarViaWS({
  meetingToken,
  text,
  avatar,
  emotion,
  language,
  increaseResolution = false,
}) {
  if (!settings.avatartalk_api_key) {
    throw new Error('AVATARTALK_API_KEY is not set');
  }
  const base = settings.avatartalk_ws_base_url.replace(/\/$/, '');
  const qs = new URLSearchParams({
    output_type: 'livekit',
    input_type: 'text',
    avatar: avatar || settings.avatar,
    emotion: emotion || settings.emotion,
    language: language || settings.language,
    meeting_token: meetingToken,
    increase_resolution: increaseResolution ? 'true' : 'false',
  });
  if (settings.livekit_url) qs.set('livekit_url', settings.livekit_url);
  const url = `${base}/ws/infer?${qs.toString()}`;

  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url, {
      headers: { Authorization: `Bearer ${settings.avatartalk_api_key}` },
      perMessageDeflate: false,
    });

    let settled = false;
    const finish = (err) => {
      if (settled) return; settled = true;
      try { ws.close(); } catch {}
      if (err) reject(err); else resolve();
    };

    ws.on('open', () => {
      try {
        ws.send(Buffer.from(text || '', 'utf8'));
        ws.send(Buffer.from('!!!Close!!!'));
      } catch (e) {
        finish(e);
      }
    });
    ws.on('error', (e) => finish(e));
    ws.on('close', () => finish());
    // Safety timeout
    setTimeout(() => finish(), 30000).unref?.();
  });
}

