import WebSocket from 'ws';
import { config } from './config.js';
import { Logger } from './logger.js';

const DEFAULT_API_URL = 'wss://api.avatartalk.ai';

export class AvatarTalkConnector {
  constructor({
    url = config.avatartalk_url || DEFAULT_API_URL,
    apiKey = config.avatartalk_api_key,
    avatar = config.avatartalk_avatar,
    language = config.avatartalk_language,
    rtmpUrl = config.youtube_rtmp_url,
    streamKey = config.youtube_stream_key,
    roomName = 'avatartalk-live',
    increaseResolution = true,
    logger = new Logger('INFO'),
  } = {}) {
    if (!rtmpUrl || !streamKey) {
      throw new Error('YOUTUBE_RTMP_URL and YOUTUBE_STREAM_KEY are required for RTMP output');
    }
    this.apiUrl = url || DEFAULT_API_URL;
    this.apiKey = apiKey;
    this.avatar = avatar;
    this.language = language || 'en';
    this.roomName = roomName;
    this.increaseResolution = !!increaseResolution;
    this.logger = logger;
    this._ws = null;

    const qs = new URLSearchParams({
      output_type: 'rtmp',
      input_type: 'text',
      stream_id: this.roomName,
      avatar: this.avatar || '',
      emotion: 'neutral',
      language: this.language,
      increase_resolution: this.increaseResolution ? 'true' : 'false',
      rtmp_url: `${rtmpUrl.replace(/\/$/, '')}/${streamKey}`,
    });
    this.url = `${this.apiUrl.replace(/\/$/, '')}/ws/infer?${qs.toString()}`;
  }

  async initialize() {
    if (!this.apiKey) throw new Error('AVATARTALK_API_KEY is required');
    await new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url, {
        headers: { 'X-API-Key': this.apiKey },
        perMessageDeflate: false,
      });
      let settled = false;
      const finish = (err) => { if (settled) return; settled = true; err ? reject(err) : resolve(); };
      ws.once('open', () => finish());
      ws.once('error', (e) => finish(e));
      this._ws = ws;
    });
  }

  async send(textContent) {
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) throw new Error('WebSocket not initialized');
    const buf = Buffer.from(String(textContent || ''), 'utf8');
    this._ws.send(buf);
  }

  async receive(timeoutMs = 5000) {
    if (!this._ws) throw new Error('WebSocket not initialized');
    // Keep waiting until we get a JSON payload from the server
    // similar to the Python loop with a 5s timeout between tries.
    for (;;) {
      const msg = await waitForMessage(this._ws, timeoutMs, this.logger);
      try {
        const parsed = JSON.parse(msg.toString('utf8'));
        return parsed;
      } catch (e) {
        this.logger.debug('Non-JSON or timeout from AvatarTalk; retrying');
        await new Promise((r) => setTimeout(r, 5000));
      }
    }
  }

  async close() {
    if (!this._ws) return;
    try {
      try { this._ws.send(Buffer.from('!!!Close!!!')); } catch {}
    } finally {
      try { this._ws.close(); } catch {}
    }
  }
}

function waitForMessage(ws, timeoutMs, logger) {
  return new Promise((resolve, reject) => {
    let timer = null;
    const onMessage = (data) => {
      cleanup(); resolve(data);
    };
    const onError = (err) => { cleanup(); reject(err); };
    const onClose = () => { cleanup(); reject(new Error('WebSocket closed')); };
    const onTimeout = () => {
      cleanup();
      logger?.debug?.('No message received within timeout; retrying soon');
      // Return an empty object to keep loop semantics similar to Python
      resolve(Buffer.from('{}', 'utf8'));
    };
    const cleanup = () => {
      ws.off('message', onMessage);
      ws.off('error', onError);
      ws.off('close', onClose);
      if (timer) clearTimeout(timer);
    };
    ws.once('message', onMessage);
    ws.once('error', onError);
    ws.once('close', onClose);
    timer = setTimeout(onTimeout, timeoutMs);
  });
}
