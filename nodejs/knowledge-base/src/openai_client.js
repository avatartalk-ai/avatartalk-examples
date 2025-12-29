import OpenAI from 'openai';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { settings } from './config.js';

function buildOpenAIClient() {
  if (!settings.openai_api_key) {
    throw new Error('OPENAI_API_KEY is not set');
  }
  return new OpenAI({ apiKey: settings.openai_api_key });
}

export async function responsesWithFileSearch(messages, vectorStoreId, model = undefined) {
  const client = buildOpenAIClient();
  const mdl = model || settings.openai_model;
  const resp = await client.responses.create({
    model: mdl,
    input: messages,
    temperature: 0.7,
    tools: [{ type: 'file_search', vector_store_ids: [vectorStoreId] }],
  });
  // Prefer output_text when available, fallback to nested structure
  const text = resp.output_text
    || resp.output?.[0]?.content?.[0]?.text
    || resp.output?.[1]?.content?.[0]?.text
    || '';
  return String(text || '');
}

export async function transcribeAudioBuffer(buffer, filename = 'audio.webm', model = undefined) {
  const client = buildOpenAIClient();
  const mdl = model || settings.openai_stt_model;

  // Persist to a temp file so the SDK can infer type/filename
  const ext = path.extname(filename) || '.webm';
  const tmpPath = path.join(
    os.tmpdir(),
    `at-ptt-${Date.now()}-${Math.random().toString(36).slice(2)}${ext}`,
  );
  await fs.promises.writeFile(tmpPath, buffer);

  try {
    const fileStream = fs.createReadStream(tmpPath);
    const tr = await client.audio.transcriptions.create({
      model: mdl,
      file: fileStream,
    });
    return tr?.text || '';
  } finally {
    try { await fs.promises.unlink(tmpPath); } catch {}
  }
}

export function getOpenAI() {
  return buildOpenAIClient();
}

