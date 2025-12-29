import express from 'express';
import expressWs from 'express-ws';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { settings, LANGUAGE_CHOICES } from './config.js';
import { ConversationOrchestrator } from './orchestrator.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
expressWs(app);

// Setup view engine for templates
const templatesDir = path.resolve(__dirname, '..', 'templates');
app.set('views', templatesDir);
app.set('view engine', 'ejs');

// Serve static files
const staticDir = path.resolve(__dirname, '..', 'static');
app.use(settings.ROOT_PATH + '/static', express.static(staticDir));

// CORS middleware
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', '*');
  res.header('Access-Control-Allow-Headers', '*');
  next();
});

// Root endpoint - serve index.html with ROOT_PATH
app.get('/', (req, res) => {
  res.render('index', {
    root_path: settings.ROOT_PATH,
  });
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    service: 'expressive-webchat',
  });
});

// Languages endpoint
app.get('/api/languages', (req, res) => {
  const languages = LANGUAGE_CHOICES.map(({ code, name }) => ({ code, name }));
  res.json({
    languages,
    default: 'en',
  });
});

/**
 * Unified conversation WebSocket.
 *
 * This endpoint handles:
 * - Text control messages (JSON) from browser (init, audio_config, buffer_status)
 * - Binary audio data from browser microphone
 * - Text control messages (JSON) to browser (status, session_ready)
 * - Binary video data to browser (MP4 chunks from AvatarTalk)
 */
app.ws(settings.ROOT_PATH + '/ws/conversation', async (ws, req) => {
  console.log('[App] Client connected to /ws/conversation');

  const orchestrator = new ConversationOrchestrator();
  let initialized = false;
  let initTimeout = null;

  /**
   * Send status update to browser (JSON text frame).
   * @param {string} status
   */
  async function sendStatus(status) {
    try {
      if (ws.readyState === ws.OPEN) {
        ws.send(JSON.stringify({ type: 'status', data: status }));
      }
    } catch (e) {
      console.error('[App] Error sending status to browser:', e);
    }
  }

  /**
   * Send session ready notification to browser (JSON text frame).
   * @param {string} sessionId
   */
  async function sendSessionReady(sessionId) {
    try {
      if (ws.readyState === ws.OPEN) {
        ws.send(
          JSON.stringify({
            type: 'session_ready',
            data: { session_id: sessionId },
          })
        );
      }
    } catch (e) {
      console.error('[App] Error sending session_ready to browser:', e);
    }
  }

  /**
   * Forward video data to browser (binary frame).
   * @param {Buffer} videoBytes
   */
  async function sendVideoData(videoBytes) {
    try {
      if (ws.readyState === ws.OPEN) {
        ws.send(videoBytes);
      }
    } catch (e) {
      console.error('[App] Error sending video data to browser:', e);
    }
  }

  /**
   * Send error to browser.
   * @param {string} message
   */
  function sendError(message) {
    try {
      if (ws.readyState === ws.OPEN) {
        ws.send(JSON.stringify({ type: 'error', data: message }));
      }
    } catch (e) {
      console.error('[App] Error sending error to browser:', e);
    }
  }

  // Set up orchestrator callbacks
  orchestrator.onStatusChange = sendStatus;
  orchestrator.onSessionReady = sendSessionReady;
  orchestrator.onVideoData = sendVideoData;

  // Set up init message timeout
  initTimeout = setTimeout(() => {
    if (!initialized) {
      console.warn(`[App] Init message timeout after ${settings.INIT_MESSAGE_TIMEOUT}ms`);
      sendError('Initialization timeout');
      ws.close();
    }
  }, settings.INIT_MESSAGE_TIMEOUT);

  ws.on('message', async (data) => {
    try {
      // In express-ws, binary data comes as Buffer, text as string
      // Check if it's binary audio data (Buffer that doesn't start with '{')
      const isBinaryData = Buffer.isBuffer(data) && (data.length === 0 || data[0] !== 0x7b);

      if (isBinaryData) {
        // Binary audio frames
        await orchestrator.processAudio(data);
      } else {
        // Text control messages (JSON)
        let msg;
        try {
          const textData = Buffer.isBuffer(data) ? data.toString() : data;
          msg = JSON.parse(textData);
        } catch (e) {
          console.warn('[App] Invalid JSON message received');
          return;
        }

        const msgType = msg.type;
        const payload = msg.data || {};

        if (msgType === 'init') {
          if (initialized) {
            console.warn('[App] Already initialized, ignoring duplicate init');
            return;
          }

          clearTimeout(initTimeout);
          initialized = true;

          const avatar = String(payload.avatar || settings.DEFAULT_AVATAR);
          const expression = String(payload.expression || settings.DEFAULT_EXPRESSION);
          const prompt = String(payload.prompt || settings.SYSTEM_PROMPT);
          const language = String(payload.language || 'en');
          const usePregen = payload.use_pregen !== false;

          try {
            await orchestrator.startSession({
              avatar,
              expression,
              prompt,
              language,
              usePregen,
            });
          } catch (e) {
            console.error('[App] Failed to start session:', e);
            sendError(`Connection failed: ${e.message}`);
            ws.close();
            return;
          }
        } else if (msgType === 'audio_config') {
          const sampleRate = payload.sample_rate;
          const channelCount = payload.channel_count;
          console.log(
            `[App] Received audio_config from browser: sampleRate=${sampleRate}, channels=${channelCount}`
          );
          orchestrator.setAudioConfig({ sampleRate, channelCount });
        } else if (msgType === 'buffer_status') {
          const bufferedMs = payload.buffered_ms;
          const playbackPosition = payload.playback_position;
          if (bufferedMs !== undefined) {
            await orchestrator.sendBufferStatus(
              parseFloat(bufferedMs),
              parseFloat(playbackPosition || 0)
            );
          }
        }
      }
    } catch (e) {
      console.error('[App] Error processing message:', e);
    }
  });

  ws.on('close', async () => {
    console.log('[App] Client disconnected');
    clearTimeout(initTimeout);
    try {
      await orchestrator.stopSession();
    } catch (e) {
      console.error('[App] Error stopping session:', e);
    }
  });

  ws.on('error', (error) => {
    console.error('[App] WebSocket error:', error);
  });
});

// Start server
app.listen(settings.PORT, settings.HOST, () => {
  console.log(`AvatarTalk Expressive WebChat listening on http://${settings.HOST}:${settings.PORT}`);
});
