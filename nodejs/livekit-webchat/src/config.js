import dotenv from 'dotenv';

dotenv.config();

function getBool(name, def = false) {
  const v = process.env[name];
  if (v == null) return def;
  const s = String(v).trim().toLowerCase();
  return s === '1' || s === 'true' || s === 'yes' || s === 'on';
}

export const settings = Object.freeze({
  // OpenAI
  openai_api_key: process.env.OPENAI_API_KEY || null,
  openai_model: process.env.OPENAI_MODEL || 'gpt-4o-mini',
  openai_stt_model: process.env.OPENAI_STT_MODEL || 'whisper-1',

  // AvatarTalk
  avatartalk_api_key: process.env.AVATARTALK_API_KEY || process.env.AT_API_KEY || null,
  avatartalk_base_url: process.env.AVATARTALK_API_BASE || 'https://api.avatartalk.ai',
  avatartalk_ws_base_url: process.env.AVATARTALK_WS_BASE || 'wss://avatartalk.ai',

  // Defaults for inference
  avatar: process.env.AVATARTALK_AVATAR || 'european_woman',
  emotion: process.env.AVATARTALK_EMOTION || 'neutral',
  language: process.env.AVATARTALK_LANGUAGE || 'en',
  delayed: getBool('AVATARTALK_DELAYED', false),

  // Server config
  host: process.env.APP_HOST || '127.0.0.1',
  port: Number(process.env.APP_PORT || '8000'),
  debug: getBool('APP_DEBUG', true),

  // LiveKit
  livekit_url: process.env.LIVEKIT_URL || null,
  livekit_api_key: process.env.LIVEKIT_API_KEY || null,
  livekit_api_secret: process.env.LIVEKIT_API_SECRET || null,
  livekit_token_ttl_seconds: Number(process.env.LIVEKIT_TOKEN_TTL || '3600'),
});

