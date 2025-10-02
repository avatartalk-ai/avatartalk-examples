import dotenv from 'dotenv';

dotenv.config();

function getBool(name, def = false) {
  const v = process.env[name];
  if (v == null) return def;
  return String(v).trim().toLowerCase() === '1'
    || String(v).trim().toLowerCase() === 'true'
    || String(v).trim().toLowerCase() === 'yes'
    || String(v).trim().toLowerCase() === 'on';
}

export const settings = Object.freeze({
  // OpenAI
  openai_api_key: process.env.OPENAI_API_KEY || null,
  openai_model: process.env.OPENAI_MODEL || 'gpt-4o-mini',
  openai_stt_model: process.env.OPENAI_STT_MODEL || 'whisper-1',

  // AvatarTalk
  avatartalk_api_key: process.env.AVATARTALK_API_KEY || process.env.AT_API_KEY || null,
  avatartalk_base_url: process.env.AVATARTALK_API_BASE || 'https://api.avatartalk.ai',

  // Defaults
  avatar: process.env.AVATARTALK_AVATAR || 'european_woman',
  emotion: process.env.AVATARTALK_EMOTION || 'neutral',
  language: process.env.AVATARTALK_LANGUAGE || 'en',
  delayed: getBool('AVATARTALK_DELAYED', false),

  // Server
  host: process.env.APP_HOST || '127.0.0.1',
  port: Number(process.env.APP_PORT || '8000'),
  debug: getBool('APP_DEBUG', true),
});

