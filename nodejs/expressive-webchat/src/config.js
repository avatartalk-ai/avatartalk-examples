import dotenv from 'dotenv';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Validate that required environment variables are set.
 * @param {string[]} keys - List of required environment variable names
 */
function validateRequired(keys) {
  const missing = keys.filter((key) => !process.env[key]);
  if (missing.length > 0) {
    console.error(`Missing required environment variables: ${missing.join(', ')}`);
    console.error('Please set these in your .env file. See .env.example for reference.');
    process.exit(1);
  }
}

validateRequired(['OPENAI_API_KEY', 'DEEPGRAM_API_KEY', 'AVATARTALK_API_KEY']);

/**
 * ASR model enum for speech recognition.
 * @readonly
 * @enum {string}
 */
export const ASRModel = Object.freeze({
  NOVA3: 'nova-3', // Multilingual, use endpointing for turn detection
  NOVA2: 'nova-2', // Single-language models for unsupported Nova-3 languages
});

/**
 * Expression enum for avatar emotional responses.
 * @readonly
 * @enum {string}
 */
export const Expression = Object.freeze({
  HAPPY: 'happy',
  NEUTRAL: 'neutral',
  SERIOUS: 'serious',
});

/**
 * Get list of valid expression values.
 * @returns {string[]}
 */
export function getExpressionValues() {
  return Object.values(Expression);
}

/**
 * Get default expression.
 * @returns {string}
 */
export function getDefaultExpression() {
  return Expression.NEUTRAL;
}

/**
 * Language configuration with ASR model mapping.
 * Format: { code, name, asrModel, deepgramCode }
 * Nova-3 supports most languages, Nova-2 for others.
 */
export const LANGUAGE_CHOICES = [
  { code: 'en', name: 'English', asrModel: ASRModel.NOVA3, deepgramCode: 'en' },
  { code: 'es', name: 'Spanish', asrModel: ASRModel.NOVA3, deepgramCode: 'es' },
  { code: 'fr', name: 'French', asrModel: ASRModel.NOVA3, deepgramCode: 'fr' },
  { code: 'de', name: 'German', asrModel: ASRModel.NOVA3, deepgramCode: 'de' },
  { code: 'it', name: 'Italian', asrModel: ASRModel.NOVA3, deepgramCode: 'it' },
  { code: 'pt', name: 'Portuguese', asrModel: ASRModel.NOVA3, deepgramCode: 'pt' },
  { code: 'pl', name: 'Polish', asrModel: ASRModel.NOVA3, deepgramCode: 'pl' },
  { code: 'tr', name: 'Turkish', asrModel: ASRModel.NOVA3, deepgramCode: 'tr' },
  { code: 'ru', name: 'Russian', asrModel: ASRModel.NOVA3, deepgramCode: 'ru' },
  { code: 'nl', name: 'Dutch', asrModel: ASRModel.NOVA3, deepgramCode: 'nl' },
  { code: 'cs', name: 'Czech', asrModel: ASRModel.NOVA3, deepgramCode: 'cs' },
  // { code: 'ar', name: 'Arabic', asrModel: ASRModel.NOVA3, deepgramCode: 'ar' },
  // { code: 'cn', name: 'Chinese', asrModel: ASRModel.NOVA2, deepgramCode: 'zh' },
  { code: 'ja', name: 'Japanese', asrModel: ASRModel.NOVA3, deepgramCode: 'ja' },
  { code: 'hu', name: 'Hungarian', asrModel: ASRModel.NOVA3, deepgramCode: 'hu' },
  { code: 'ko', name: 'Korean', asrModel: ASRModel.NOVA3, deepgramCode: 'ko' },
  { code: 'hi', name: 'Hindi', asrModel: ASRModel.NOVA3, deepgramCode: 'hi' },
];

/**
 * Get language configuration by code.
 * @param {string} code
 * @returns {{ code: string, name: string, asrModel: string, deepgramCode: string } | undefined}
 */
export function getLanguageConfig(code) {
  return LANGUAGE_CHOICES.find((lang) => lang.code === code);
}

/**
 * Get the ASR model to use for a given language code.
 * @param {string} code
 * @returns {string}
 */
export function getASRModelForLanguage(code) {
  const config = getLanguageConfig(code);
  return config?.asrModel || ASRModel.NOVA3;
}

/**
 * Get Deepgram language code for a given language code.
 * @param {string} code
 * @returns {string}
 */
export function getDeepgramLanguageCode(code) {
  const config = getLanguageConfig(code);
  return config?.deepgramCode || 'en';
}

/**
 * Get language display name.
 * @param {string} code
 * @returns {string}
 */
export function getLanguageDisplayName(code) {
  const config = getLanguageConfig(code);
  return config?.name || 'English';
}

/**
 * Load localized messages from JSON file.
 * @param {string} filename
 * @returns {Object<string, string>}
 */
function loadMessages(filename) {
  const dataDir = path.resolve(__dirname, '..', 'data');
  const filepath = path.join(dataDir, filename);
  try {
    const content = fs.readFileSync(filepath, 'utf-8');
    return JSON.parse(content);
  } catch (e) {
    console.warn(`Failed to load ${filename}:`, e.message);
    return {};
  }
}

const ERROR_MESSAGES = loadMessages('error_message.json');
const TIMEOUT_MESSAGES = loadMessages('timeout_message.json');

/**
 * Get localized error message.
 * @param {string} languageCode
 * @returns {string}
 */
export function getErrorMessage(languageCode) {
  return ERROR_MESSAGES[languageCode] || ERROR_MESSAGES['en'] || "I'm sorry, I encountered an error. Please try again.";
}

/**
 * Get localized timeout message.
 * @param {string} languageCode
 * @returns {string}
 */
export function getTimeoutMessage(languageCode) {
  return TIMEOUT_MESSAGES[languageCode] || TIMEOUT_MESSAGES['en'] || "I'm sorry, I'm taking too long to respond. Please try again.";
}

/**
 * @typedef {Object} Settings
 * @property {string} OPENAI_API_KEY
 * @property {string} DEEPGRAM_API_KEY
 * @property {string} AVATARTALK_API_KEY
 * @property {string} AVATARTALK_API_BASE
 * @property {string} DEFAULT_AVATAR
 * @property {string} DEFAULT_EXPRESSION
 * @property {string} LLM_MODEL
 * @property {string} SYSTEM_PROMPT
 * @property {number} WS_CONNECT_TIMEOUT
 * @property {number} LLM_TIMEOUT
 * @property {number} INIT_MESSAGE_TIMEOUT
 * @property {number} MAX_PROMPT_LENGTH
 * @property {string} ROOT_PATH
 * @property {string} HOST
 * @property {number} PORT
 */

/** @type {Settings} */
export const settings = Object.freeze({
  // API Keys (required)
  OPENAI_API_KEY: process.env.OPENAI_API_KEY,
  DEEPGRAM_API_KEY: process.env.DEEPGRAM_API_KEY,
  AVATARTALK_API_KEY: process.env.AVATARTALK_API_KEY,

  // AvatarTalk API
  AVATARTALK_API_BASE: process.env.AVATARTALK_API_BASE || 'wss://api.avatartalk.ai',

  // Defaults
  DEFAULT_AVATAR: process.env.DEFAULT_AVATAR || 'mexican_woman',
  DEFAULT_EXPRESSION: process.env.DEFAULT_EXPRESSION || 'neutral',

  // LLM
  LLM_MODEL: process.env.LLM_MODEL || 'gpt-4o-mini',
  SYSTEM_PROMPT:
    process.env.SYSTEM_PROMPT ||
    'You are a helpful and friendly AI avatar. Keep your responses concise and conversational.',

  // Timeouts (seconds -> milliseconds for JS)
  WS_CONNECT_TIMEOUT: parseFloat(process.env.WS_CONNECT_TIMEOUT || '30') * 1000,
  LLM_TIMEOUT: parseFloat(process.env.LLM_TIMEOUT || '60') * 1000,
  INIT_MESSAGE_TIMEOUT: parseFloat(process.env.INIT_MESSAGE_TIMEOUT || '30') * 1000,

  // Limits
  MAX_PROMPT_LENGTH: parseInt(process.env.MAX_PROMPT_LENGTH || '4000', 10),

  // API settings
  ROOT_PATH: process.env.ROOT_PATH || '',

  // Server
  HOST: process.env.APP_HOST || '127.0.0.1',
  PORT: parseInt(process.env.APP_PORT || '8080', 10),
});
