import { settings } from './config.js';

export class AvatarTalkError extends Error {}

export async function inference(text, opts = {}) {
  if (!settings.avatartalk_api_key) {
    throw new Error('AVATARTALK_API_KEY is not set');
  }
  const base = settings.avatartalk_base_url.replace(/\/$/, '');
  const url = `${base}/inference`;

  const payload = {
    text,
    avatar: opts.avatar || settings.avatar,
    emotion: opts.emotion || settings.emotion,
    language: opts.language || settings.language,
  };

  const useDelayed = opts.delayed !== undefined ? opts.delayed : settings.delayed;
  if (useDelayed) payload.delayed = true;

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${settings.avatartalk_api_key}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new AvatarTalkError(`AvatarTalk inference failed: ${res.status} ${text}`);
  }
  return res.json();
}

