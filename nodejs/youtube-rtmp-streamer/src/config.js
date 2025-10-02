import dotenv from 'dotenv';

dotenv.config();

function getEnv(name, def = null) {
  const v = process.env[name];
  return v == null || v === '' ? def : v;
}

export const config = Object.freeze({
  // AvatarTalk
  avatartalk_url: getEnv('AVATARTALK_URL', 'wss://api.avatartalk.ai'),
  avatartalk_api_key: getEnv('AVATARTALK_API_KEY'),
  avatartalk_avatar: getEnv('AVATARTALK_AVATAR', 'european_woman'),
  avatartalk_language: getEnv('AVATARTALK_LANGUAGE', 'en'),

  // YouTube Data API + RTMP ingest
  youtube_api_key: getEnv('YOUTUBE_API_KEY'),
  youtube_rtmp_url: getEnv('YOUTUBE_RTMP_URL'),
  youtube_stream_key: getEnv('YOUTUBE_STREAM_KEY'),
  youtube_live_id: getEnv('YOUTUBE_LIVE_ID'),

  // OpenAI
  openai_api_key: getEnv('OPENAI_API_KEY'),
  avatartalk_model: getEnv('AVATARTALK_MODEL', 'gpt-4o-mini'),

  // Topics
  topics_file: getEnv('AVATARTALK_TOPICS_FILE', 'topics.txt'),
});

