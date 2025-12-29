import WebSocket from 'ws';

const DEFAULT_CONNECT_TIMEOUT = 30000;
const DEFAULT_CLOSE_TIMEOUT = 5000;

/**
 * Client for AvatarTalk WebSocket streaming.
 *
 * Uses a single WebSocket connection for both control messages (JSON text frames)
 * and video streaming (binary frames).
 *
 * Authentication: Bearer token via `Authorization: Bearer <AVATARTALK_API_KEY>` header.
 */
export class AvatarTalkClient {
  /**
   * @param {string} url - Base WebSocket URL (e.g., wss://api.avatartalk.ai)
   * @param {string} apiKey - Bearer token for authentication
   * @param {number} connectTimeout - Connection timeout in milliseconds
   */
  constructor(url, apiKey = '', connectTimeout = DEFAULT_CONNECT_TIMEOUT) {
    this.url = url.replace(/\/$/, '');
    this.apiKey = apiKey;
    this.connectTimeout = connectTimeout;
    /** @type {WebSocket | null} */
    this.ws = null;
    /** @type {string | null} */
    this.sessionId = null;
    this._connected = false;
    this._closing = false;

    // Connection params
    /** @type {string | null} */
    this._avatar = null;
    /** @type {string | null} */
    this._expression = null;
    /** @type {string} */
    this._language = 'en';

    // Callbacks
    /** @type {((from: string, to: string) => Promise<void>) | null} */
    this.onStateChange = null;
    /** @type {(() => Promise<void>) | null} */
    this.onReadyToListen = null;
    /** @type {((sessionId: string) => Promise<void>) | null} */
    this.onSessionReady = null;
    /** @type {((error: string) => Promise<void>) | null} */
    this.onError = null;
    /** @type {(() => Promise<void>) | null} */
    this.onDisconnect = null;
    /** @type {((data: Buffer) => Promise<void>) | null} */
    this.onVideoData = null;
  }

  /**
   * Connect to the AvatarTalk WebSocket endpoint.
   * @param {Object} options
   * @param {string} [options.avatar]
   * @param {string} [options.expression]
   * @param {string} [options.language='en']
   */
  async connect({ avatar, expression, language = 'en' } = {}) {
    this._avatar = avatar || null;
    this._expression = expression || null;
    this._language = language;

    const queryParams = new URLSearchParams();
    if (avatar) queryParams.set('avatar', avatar);
    if (expression) queryParams.set('expression', expression);
    if (language) queryParams.set('language', language);

    let uri = `${this.url}/ws/continuous`;
    const qs = queryParams.toString();
    if (qs) uri += `?${qs}`;

    const headers = {};
    if (this.apiKey) {
      headers['Authorization'] = `Bearer ${this.apiKey}`;
      console.log(`[AvatarTalk] Connecting to: ${uri} (auth: Bearer token)`);
    } else {
      console.warn(`[AvatarTalk] Connecting without authentication: ${uri}`);
    }

    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        if (this.ws) {
          this.ws.terminate();
          this.ws = null;
        }
        reject(new Error(`Connection timeout after ${this.connectTimeout}ms`));
      }, this.connectTimeout);

      this.ws = new WebSocket(uri, { headers });

      this.ws.on('open', () => {
        clearTimeout(timeoutId);
        this._connected = true;
        this._closing = false;
        console.log('[AvatarTalk] WebSocket connected');
        resolve();
      });

      this.ws.on('message', async (data, isBinary) => {
        if (isBinary) {
          // Binary frame - video data
          if (this.onVideoData) {
            await this.onVideoData(data);
          }
        } else {
          // Text frame - JSON control message
          try {
            const msg = JSON.parse(data.toString());
            await this._handleControlMessage(msg);
          } catch (e) {
            console.error('[AvatarTalk] Error parsing message:', e);
          }
        }
      });

      this.ws.on('close', async (code, reason) => {
        clearTimeout(timeoutId);
        if (!this._closing) {
          console.warn(`[AvatarTalk] Connection closed unexpectedly: ${code} ${reason}`);
        } else {
          console.log(`[AvatarTalk] Connection closed: ${code}`);
        }
        this._connected = false;
        if (this.onDisconnect && !this._closing) {
          try {
            await this.onDisconnect();
          } catch (e) {
            console.error('[AvatarTalk] Error in disconnect callback:', e);
          }
        }
      });

      this.ws.on('error', (error) => {
        clearTimeout(timeoutId);
        console.error('[AvatarTalk] WebSocket error:', error.message);
        reject(new Error(`WebSocket connection failed: ${error.message}`));
      });
    });
  }

  /**
   * Handle incoming control messages
   * @param {Object} msg
   */
  async _handleControlMessage(msg) {
    const msgType = msg.type;
    const msgData = msg.data || {};

    switch (msgType) {
      case 'session_ready':
        this.sessionId = msgData.session_id;
        console.log(`[AvatarTalk] Session Ready: ${this.sessionId}`);
        if (this.onSessionReady && this.sessionId) {
          await this.onSessionReady(this.sessionId);
        }
        break;

      case 'state_change':
        if (this.onStateChange) {
          await this.onStateChange(msgData.from, msgData.to);
        }
        break;

      case 'ready_to_listen':
        if (this.onReadyToListen) {
          await this.onReadyToListen();
        }
        break;

      case 'error':
        const errorMsg = msgData.message || 'Unknown error';
        console.error(`[AvatarTalk] Error: ${errorMsg}`);
        if (this.onError) {
          await this.onError(errorMsg);
        }
        break;

      case 'text_queued':
      case 'text_appended':
      case 'text_stream_completed':
      case 'turn_queued':
      case 'pong':
      case 'buffer_warning':
        // Acknowledgments/status - no action needed
        break;

      default:
        // Only log truly unknown message types
        console.warn(`[AvatarTalk] Unhandled message type: ${msgType}`);
    }
  }

  _checkConnected() {
    if (!this._connected || !this.ws) {
      throw new Error('Not connected to AvatarTalk API');
    }
  }

  /**
   * Start a new streaming session.
   * @param {Object} options
   * @param {string} options.avatar
   * @param {string} options.expression
   * @param {string} [options.language='en']
   * @param {boolean} [options.expressiveMode=false]
   * @param {number} [options.targetBufferMs=500]
   * @param {number} [options.minBufferMs=250]
   * @param {number} [options.maxBufferMs=1500]
   */
  async startSession({
    avatar,
    expression,
    language = 'en',
    expressiveMode = false,
    targetBufferMs = 500,
    minBufferMs = 250,
    maxBufferMs = 1500,
  }) {
    this._checkConnected();

    const data = {
      avatar_name: avatar,
      expression,
      language,
      expressive_mode: expressiveMode,
      target_buffer_ms: targetBufferMs,
      min_buffer_ms: minBufferMs,
      max_buffer_ms: maxBufferMs,
    };

    const msg = { type: 'session_start', data };
    console.log(`[AvatarTalk] Sending session_start: avatar=${avatar}, expression=${expression}`);
    this.ws.send(JSON.stringify(msg));
  }

  /**
   * Send text to be spoken.
   * @param {string} text
   * @param {Object} [options]
   * @param {string} [options.expression]
   * @param {string} [options.mode]
   */
  async sendText(text, { expression, mode } = {}) {
    this._checkConnected();

    const data = { text };
    if (expression !== undefined) data.expression = expression;
    if (mode !== undefined) data.mode = mode;

    const msg = { type: 'text_input', data };
    this.ws.send(JSON.stringify(msg));
  }

  /**
   * Trigger an End-of-Turn pregenerated segment.
   * @param {Object} [options]
   * @param {string} [options.expression]
   */
  async sendTurnStart({ expression } = {}) {
    this._checkConnected();

    const data = {};
    if (expression !== undefined) data.expression = expression;

    const msg = { type: 'turn_start', data };
    this.ws.send(JSON.stringify(msg));
  }

  /**
   * Append additional text to an ongoing dynamic speech generation.
   * @param {string} text
   */
  async appendText(text) {
    this._checkConnected();

    const msg = { type: 'text_append', data: { text } };
    this.ws.send(JSON.stringify(msg));
  }

  /**
   * Signal that no more text will be appended.
   */
  async finishTextStream() {
    this._checkConnected();

    const msg = { type: 'text_stream_done', data: {} };
    this.ws.send(JSON.stringify(msg));
  }

  /**
   * Send client-side video buffer status for adaptive streaming.
   * @param {number} bufferedMs
   * @param {number} playbackPosition
   */
  async sendBufferStatus(bufferedMs, playbackPosition) {
    this._checkConnected();

    const msg = {
      type: 'buffer_status',
      data: {
        buffered_ms: bufferedMs,
        playback_position: playbackPosition,
      },
    };
    this.ws.send(JSON.stringify(msg));
  }

  /**
   * Gracefully disconnect from the AvatarTalk API.
   */
  async disconnect() {
    if (this._closing) return;
    this._closing = true;
    this._connected = false;

    if (this.ws) {
      return new Promise((resolve) => {
        const timeoutId = setTimeout(() => {
          console.warn('[AvatarTalk] Timeout closing WebSocket, forcing close');
          if (this.ws) {
            this.ws.terminate();
            this.ws = null;
          }
          resolve();
        }, DEFAULT_CLOSE_TIMEOUT);

        this.ws.once('close', () => {
          clearTimeout(timeoutId);
          this.ws = null;
          resolve();
        });

        this.ws.close();
      });
    }

    this.sessionId = null;
    console.log('[AvatarTalk] Disconnected from AvatarTalk API');
  }
}
