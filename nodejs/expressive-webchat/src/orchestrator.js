import { createClient } from '@deepgram/sdk';
import OpenAI from 'openai';
import {
  settings,
  Expression,
  getExpressionValues,
  getDefaultExpression,
  getDeepgramLanguageCode,
  getASRModelForLanguage,
  getLanguageDisplayName,
  getErrorMessage,
  getTimeoutMessage,
} from './config.js';
import { AvatarTalkClient } from './avatartalk_client.js';

/**
 * Accumulates streaming tokens and emits complete sentences.
 * Handles JSON expression prefix extraction and sentence boundary detection.
 */
class SentenceAccumulator {
  static SENTENCE_END_PATTERN = /([.!?])(?:\s+|$)/;
  static EXPRESSION_PATTERN = /^\s*\{\s*"expression"\s*:\s*"(\w+)"\s*\}\s*\n?/;

  constructor() {
    this.buffer = '';
    this._jsonPrefixBuffer = '';
    this._jsonComplete = false;
  }

  /**
   * Try to extract expression from JSON prefix.
   * @param {string} content
   * @returns {[string|null, string]} - [expression, remaining_content]
   */
  tryExtractExpression(content) {
    if (this._jsonComplete) {
      return [null, content];
    }

    this._jsonPrefixBuffer += content;

    const match = SentenceAccumulator.EXPRESSION_PATTERN.exec(this._jsonPrefixBuffer);
    if (match) {
      const expression = match[1];
      const remaining = this._jsonPrefixBuffer.slice(match[0].length);
      this._jsonComplete = true;
      this._jsonPrefixBuffer = '';
      return [expression, remaining];
    }

    // If buffer is getting long without finding JSON, treat as regular text
    if (this._jsonPrefixBuffer.length > 100 || this._jsonPrefixBuffer.includes('\n')) {
      const remaining = this._jsonPrefixBuffer;
      this._jsonPrefixBuffer = '';
      this._jsonComplete = true;
      return [null, remaining];
    }

    return [null, ''];
  }

  /**
   * Check if we're still accumulating a potential JSON prefix.
   * @returns {boolean}
   */
  bufferHasExpressionPrefix() {
    return this._jsonPrefixBuffer.length > 0 && !this._jsonComplete;
  }

  /**
   * Add a chunk of text and return any complete sentences.
   * @param {string} content
   * @returns {string[]}
   */
  addChunk(content) {
    if (!content) return [];

    this.buffer += content;
    const sentences = [];

    while (true) {
      const match = SentenceAccumulator.SENTENCE_END_PATTERN.exec(this.buffer);
      if (!match) {
        if (this.buffer.length > 400) {
          sentences.push(this.buffer);
          this.buffer = '';
        }
        break;
      }

      const endPos = match.index + match[0].length;
      const sentence = this.buffer.slice(0, endPos).trim();
      this.buffer = this.buffer.slice(endPos);

      if (sentence) {
        sentences.push(sentence);
      }
    }

    return sentences;
  }

  /**
   * Return any remaining content in the buffer.
   * @returns {string}
   */
  flush() {
    const remaining = (this._jsonPrefixBuffer + this.buffer).trim();
    this._jsonPrefixBuffer = '';
    this.buffer = '';
    return remaining;
  }
}

/**
 * Conversation Orchestrator - coordinates Deepgram, OpenAI, and AvatarTalk.
 */
export class ConversationOrchestrator {
  constructor() {
    this.avatartalk = new AvatarTalkClient(
      settings.AVATARTALK_API_BASE,
      settings.AVATARTALK_API_KEY,
      settings.WS_CONNECT_TIMEOUT
    );
    console.log(`[Orchestrator] Initialized: url=${settings.AVATARTALK_API_BASE}`);

    // Deepgram client
    this.deepgram = createClient(settings.DEEPGRAM_API_KEY);
    this.dgConnection = null;
    this.transcriptBuffer = [];
    this.dgKeepAliveInterval = null; // KeepAlive interval to prevent NET-0001 timeout

    // OpenAI client
    this.openai = new OpenAI({ apiKey: settings.OPENAI_API_KEY });

    // State
    this.isListening = false;
    this.isAvatarSpeaking = false;
    this.sessionActive = false;
    this.avatarTurnActive = false;
    this._ignoreTranscripts = false; // Ignore transcripts during avatar's turn
    this._pauseAudioSending = false; // Gate to stop sending audio to Deepgram
    this.audioSampleRate = 16000;
    this.audioChannels = 1;
    this.audioConfigured = false;
    this.usePregen = true;

    // Expressive mode
    this.expressiveMode = false;
    this.currentExpression = getDefaultExpression();

    // Language configuration
    this.language = 'en';
    this.deepgramLanguage = 'en';
    this.asrModel = 'nova-3';

    this.conversationHistory = [];
    this.maxHistoryMessages = 30;
    this.systemPrompt = settings.SYSTEM_PROMPT;

    // Callbacks
    /** @type {((status: string) => Promise<void>) | null} */
    this.onStatusChange = null;
    /** @type {((sessionId: string) => Promise<void>) | null} */
    this.onSessionReady = null;
    /** @type {((data: Buffer) => Promise<void>) | null} */
    this.onVideoData = null;
  }

  /**
   * Start the conversation session.
   * @param {Object} options
   * @param {string} options.avatar
   * @param {string} options.expression
   * @param {string} options.prompt
   * @param {string} [options.language='en']
   * @param {boolean} [options.usePregen=true]
   */
  async startSession({ avatar, expression, prompt, language = 'en', usePregen = true }) {
    // Validate and sanitize prompt length
    if (prompt.length > settings.MAX_PROMPT_LENGTH) {
      console.warn(
        `[Orchestrator] System prompt truncated from ${prompt.length} to ${settings.MAX_PROMPT_LENGTH} chars`
      );
      prompt = prompt.slice(0, settings.MAX_PROMPT_LENGTH);
    }
    this.systemPrompt = prompt;
    this.usePregen = usePregen;

    // Configure language and ASR model
    this.language = language;
    this.deepgramLanguage = getDeepgramLanguageCode(language);
    this.asrModel = getASRModelForLanguage(language);
    console.log(
      `[Orchestrator] Language configured: ${language} -> ASR model: ${this.asrModel}, Deepgram lang: ${this.deepgramLanguage}`
    );

    // Handle expressive mode
    let effectiveExpression;
    if (expression === 'expressive') {
      this.expressiveMode = true;
      this.currentExpression = getDefaultExpression();
      effectiveExpression = getDefaultExpression();
      console.log(
        `[Orchestrator] Starting session in EXPRESSIVE mode: avatar=${avatar}, initial_expression=neutral`
      );
    } else {
      this.expressiveMode = false;
      this.currentExpression = expression;
      effectiveExpression = expression;
      console.log(
        `[Orchestrator] Starting session: avatar=${avatar}, expression=${expression}, usePregen=${usePregen}`
      );
    }

    // Connect to AvatarTalk API
    await this.avatartalk.connect({
      avatar,
      expression: effectiveExpression,
      language,
    });

    this.avatartalk.onStateChange = this._handleAvatarTalkStateChange.bind(this);
    this.avatartalk.onReadyToListen = this._handleReadyToListen.bind(this);
    this.avatartalk.onSessionReady = this._handleAvatarTalkSessionReady.bind(this);
    this.avatartalk.onVideoData = this._handleVideoData.bind(this);

    // Start AvatarTalk session
    await this.avatartalk.startSession({
      avatar,
      expression: effectiveExpression,
      language,
      expressiveMode: this.expressiveMode,
    });

    this.sessionActive = true;
  }

  /**
   * Stop the conversation session and cleanup resources.
   */
  async stopSession() {
    this.sessionActive = false;
    this.isListening = false;

    // Stop KeepAlive interval
    this._stopDgKeepAlive();

    // Close Deepgram connection
    if (this.dgConnection) {
      try {
        this.dgConnection.requestClose();
      } catch (e) {
        console.error('[Orchestrator] Error closing Deepgram connection:', e);
      }
      this.dgConnection = null;
    }

    // Disconnect from AvatarTalk
    await this.avatartalk.disconnect();
  }

  /**
   * Process incoming audio from user and send to Deepgram.
   * @param {Buffer} audioData
   */
  async processAudio(audioData) {
    if (!this.sessionActive || !this.isListening) {
      return;
    }

    if (!this.audioConfigured) {
      console.warn('[Orchestrator] Dropping audio frame because audio_config has not been received yet');
      return;
    }

    // Ensure Deepgram connection exists
    await this._ensureDeepgramConnection();

    if (!this.dgConnection) {
      console.error('[Orchestrator] Deepgram connection is not available; dropping audio chunk');
      return;
    }

    // Check audio gate - skip sending if paused (turn switched)
    if (this._pauseAudioSending) {
      return;
    }

    try {
      this.dgConnection.send(audioData);
    } catch (e) {
      console.error('[Orchestrator] Error sending audio to Deepgram:', e);
    }
  }

  /**
   * Forward browser video buffer status to AvatarTalk.
   * @param {number} bufferedMs
   * @param {number} [playbackPosition=0]
   */
  async sendBufferStatus(bufferedMs, playbackPosition = 0) {
    if (!this.avatartalk || !this.avatartalk.ws) {
      return;
    }

    try {
      await this.avatartalk.sendBufferStatus(bufferedMs, playbackPosition);
    } catch (e) {
      console.error('[Orchestrator] Error forwarding buffer_status to AvatarTalk:', e);
    }
  }

  /**
   * Set audio configuration from browser.
   * @param {Object} options
   * @param {number} [options.sampleRate]
   * @param {number} [options.channelCount]
   */
  setAudioConfig({ sampleRate, channelCount }) {
    if (sampleRate) {
      this.audioSampleRate = parseInt(sampleRate, 10);
    }
    if (channelCount) {
      this.audioChannels = parseInt(channelCount, 10);
    }

    this.audioConfigured = true;
    console.log(
      `[Orchestrator] Applied audio_config: sampleRate=${this.audioSampleRate}, channels=${this.audioChannels}`
    );
  }

  /**
   * Ensure Deepgram connection is established.
   */
  async _ensureDeepgramConnection() {
    if (this.dgConnection) {
      return;
    }

    console.log(
      `[Orchestrator] Connecting to Deepgram ${this.asrModel} with sampleRate=${this.audioSampleRate}, language=${this.deepgramLanguage}`
    );

    const connection = this.deepgram.listen.live({
      model: this.asrModel,
      language: this.deepgramLanguage,
      smart_format: true,
      encoding: 'linear16',
      sample_rate: this.audioSampleRate,
      channels: this.audioChannels,
      endpointing: 500,
      interim_results: true,
      utterance_end_ms: 1000,
    });

    this.dgConnection = connection;

    connection.on('open', () => {
      console.log('[Orchestrator] Deepgram connection opened');
      // Start KeepAlive interval to prevent NET-0001 timeout (10s without audio)
      this._startDgKeepAlive(connection);
    });

    connection.on('Results', (data) => {
      // Check if this is a from_finalize response (ignore it)
      if (data.from_finalize) {
        console.log('[Orchestrator] Ignoring from_finalize response');
        return;
      }

      // Ignore transcripts during avatar's turn
      if (this._ignoreTranscripts) {
        console.log('[Orchestrator] Ignoring transcript during avatar turn');
        return;
      }

      const transcript = data.channel?.alternatives?.[0]?.transcript;
      if (!transcript) return;

      const isFinal = data.is_final;
      const speechFinal = data.speech_final;

      if (isFinal && transcript.trim()) {
        this.transcriptBuffer.push(transcript);
        console.log(`[Orchestrator] Deepgram transcript (final): ${transcript}`);
      }

      // End of utterance - process the full transcript
      if (speechFinal && this.transcriptBuffer.length > 0) {
        const fullTranscript = this.transcriptBuffer.join(' ').trim();
        // SET FLAGS SYNCHRONOUSLY before calling async handler
        // This prevents race condition where more audio/transcripts
        // arrive before the async handler runs
        this._ignoreTranscripts = true;
        this._pauseAudioSending = true;
        this.transcriptBuffer = [];
        console.log('[Orchestrator] Turn switch: flags set synchronously, scheduling handler');
        if (fullTranscript) {
          console.log(`[Orchestrator] End of utterance detected: "${fullTranscript}"`);
          this._handleUserTurn(fullTranscript).catch((e) => {
            console.error('[Orchestrator] Error handling user turn:', e);
          });
        }
      }
    });

    connection.on('UtteranceEnd', () => {
      // Ignore during avatar's turn
      if (this._ignoreTranscripts) {
        console.log('[Orchestrator] Ignoring UtteranceEnd during avatar turn');
        return;
      }

      // Backup utterance end detection
      if (this.transcriptBuffer.length > 0) {
        const fullTranscript = this.transcriptBuffer.join(' ').trim();
        // SET FLAGS SYNCHRONOUSLY before calling async handler
        this._ignoreTranscripts = true;
        this._pauseAudioSending = true;
        this.transcriptBuffer = [];
        console.log('[Orchestrator] Turn switch: flags set synchronously, scheduling handler');
        if (fullTranscript) {
          console.log(`[Orchestrator] UtteranceEnd detected: "${fullTranscript}"`);
          this._handleUserTurn(fullTranscript).catch((e) => {
            console.error('[Orchestrator] Error handling user turn:', e);
          });
        }
      }
    });


    connection.on('close', () => {
      console.log('[Orchestrator] Deepgram connection closed');
      this._stopDgKeepAlive();
      this.dgConnection = null;
    });

    connection.on('error', (error) => {
      console.error('[Orchestrator] Deepgram error:', error);
    });
  }

  /**
   * Start KeepAlive interval for Deepgram connection.
   * Sends KeepAlive every 5 seconds to prevent NET-0001 timeout.
   * @param {Object} connection - Deepgram live connection
   */
  _startDgKeepAlive(connection) {
    this._stopDgKeepAlive(); // Clear any existing interval
    this.dgKeepAliveInterval = setInterval(() => {
      try {
        if (connection && this.dgConnection) {
          connection.keepAlive();
          // console.log('[Orchestrator] Deepgram KeepAlive sent');
        }
      } catch (e) {
        console.warn('[Orchestrator] Failed to send Deepgram KeepAlive:', e.message);
      }
    }, 5000);
  }

  /**
   * Stop KeepAlive interval for Deepgram connection.
   */
  _stopDgKeepAlive() {
    if (this.dgKeepAliveInterval) {
      clearInterval(this.dgKeepAliveInterval);
      this.dgKeepAliveInterval = null;
    }
  }

  /**
   * Handle detected user speech with streaming LLM response.
   * @param {string} text
   */
  async _handleUserTurn(text) {
    // Note: _ignoreTranscripts and _pauseAudioSending are already set
    // synchronously in the event handler before this was called
    this.isListening = false;
    this.avatarTurnActive = true;

    // Send Finalize to Deepgram to flush any buffered audio on server side
    // This ensures no leftover transcripts arrive after turn switch
    this._sendDeepgramFinalize();

    if (this.onStatusChange) {
      await this.onStatusChange('thinking');
    }

    // Trigger pregenerated segment if enabled
    if (this.usePregen) {
      try {
        await this.avatartalk.sendTurnStart({ expression: this.currentExpression });
      } catch (e) {
        console.error('[Orchestrator] Error sending turn_start to AvatarTalk:', e);
      }
    }

    // Stream LLM response
    try {
      let firstSentence = true;
      let expressionUsed = this.currentExpression;

      for await (const { sentence, expression } of this._streamResponse(text)) {
        if (!sentence.trim()) continue;

        if (firstSentence) {
          if (this.expressiveMode) {
            console.log(
              `[Orchestrator] Expressive mode: LLM expression=${expression}, current=${this.currentExpression}`
            );
            expressionUsed = expression || this.currentExpression;
            if (expression) {
              this.currentExpression = expression;
              console.log(`[Orchestrator] Expressive mode: switching to '${expression}'`);
            }
          } else {
            expressionUsed = this.currentExpression;
          }

          console.log(`[Orchestrator] Avatar starting reply: ${sentence} (${expressionUsed})`);
          await this.avatartalk.sendText(sentence, {
            expression: expressionUsed,
            mode: 'dynamic_only',
          });
          firstSentence = false;
        } else {
          console.log(`[Orchestrator] Avatar appending: ${sentence}`);
          await this.avatartalk.appendText(sentence);
        }
      }

      // Signal LLM streaming complete
      if (!firstSentence) {
        await this.avatartalk.finishTextStream();
        console.log('[Orchestrator] LLM streaming complete, signaled server');
        this.avatarTurnActive = false;
      }
    } catch (e) {
      console.error('[Orchestrator] LLM streaming error:', e);
      this.isListening = true;
      this.avatarTurnActive = false;
      if (this.onStatusChange) {
        await this.onStatusChange('listening');
      }
    }
  }

  /**
   * Stream LLM response and yield complete sentences with expression.
   * @param {string} userText
   * @yields {{sentence: string, expression: string|null}}
   */
  async *_streamResponse(userText) {
    let fullResponseText = '';

    try {
      // Add language instruction if not English
      let languageInstruction = '';
      if (this.language !== 'en') {
        const langName = getLanguageDisplayName(this.language);
        languageInstruction = `\n\nIMPORTANT: You MUST respond in ${langName}. All your responses should be in ${langName}.`;
      }

      const expressionsList = getExpressionValues().join(', ');
      const messages = [
        {
          role: 'system',
          content:
            `${this.systemPrompt}${languageInstruction}\n\n` +
            'IMPORTANT: Start your response with a JSON prefix containing the expression, ' +
            'then a newline, then your natural response text.\n' +
            'Format: {"expression": "<emotion>"}\n<your response>\n\n' +
            `Expressions: ${expressionsList}\n` +
            `Example:\n{"expression": "${Expression.HAPPY}"}\nHello! It's great to meet you.`,
        },
        ...this.conversationHistory,
        { role: 'user', content: userText },
      ];

      const stream = await this.openai.chat.completions.create({
        model: settings.LLM_MODEL,
        messages,
        stream: true,
      });

      const accumulator = new SentenceAccumulator();
      let extractedExpression = null;
      let expressionExtracted = false;

      for await (const chunk of stream) {
        let content = chunk.choices[0]?.delta?.content;
        if (!content) continue;

        // Try to extract expression from JSON prefix
        if (!expressionExtracted) {
          const [exprResult, remaining] = accumulator.tryExtractExpression(content);
          if (exprResult) {
            extractedExpression = exprResult;
            expressionExtracted = true;
            content = remaining;
            console.log(`[Orchestrator] Extracted expression from LLM: '${extractedExpression}'`);
          } else if (accumulator.bufferHasExpressionPrefix()) {
            continue;
          }
        }

        // Add content and yield complete sentences
        for (const sentence of accumulator.addChunk(content)) {
          fullResponseText += sentence + ' ';
          yield { sentence, expression: extractedExpression };
          extractedExpression = null; // Only yield expression once
        }
      }

      // Yield any remaining content
      const final = accumulator.flush();
      if (final.trim()) {
        fullResponseText += final + ' ';
        yield { sentence: final, expression: null };
      }

      // Update conversation history
      this._addToHistory('user', userText);
      this._addToHistory('assistant', fullResponseText.trim());
    } catch (e) {
      if (e.name === 'AbortError') {
        console.error(`[Orchestrator] LLM response timed out after ${settings.LLM_TIMEOUT}ms`);
        yield {
          sentence: getTimeoutMessage(this.language),
          expression: getDefaultExpression(),
        };
      } else {
        console.error('[Orchestrator] Error streaming response:', e);
        yield {
          sentence: getErrorMessage(this.language),
          expression: getDefaultExpression(),
        };
      }
    }
  }

  /**
   * Add a message to conversation history.
   * @param {string} role
   * @param {string} content
   */
  _addToHistory(role, content) {
    if (!content.trim()) return;

    this.conversationHistory.push({ role, content });

    if (this.conversationHistory.length > this.maxHistoryMessages) {
      this.conversationHistory = this.conversationHistory.slice(-this.maxHistoryMessages);
    }
  }

  /**
   * Handle AvatarTalk session ready event.
   * @param {string} sessionId
   */
  async _handleAvatarTalkSessionReady(sessionId) {
    console.log(`[Orchestrator] AvatarTalk Session Ready: ${sessionId}`);
    if (this.onSessionReady) {
      await this.onSessionReady(sessionId);
    }
  }

  /**
   * Forward video data from AvatarTalk.
   * @param {Buffer} videoBytes
   */
  async _handleVideoData(videoBytes) {
    if (this.onVideoData) {
      await this.onVideoData(videoBytes);
    }
  }

  /**
   * Handle state changes from AvatarTalk server.
   * @param {string} fromState
   * @param {string} toState
   */
  async _handleAvatarTalkStateChange(fromState, toState) {
    console.log(`[Orchestrator] AvatarTalk State: ${fromState} -> ${toState}`);

    const thinkingStates = new Set(['silence_to_pregen', 'pregen_video', 'pregen_to_dynamic']);
    const speakingStates = new Set(['dynamic_speech', 'dynamic_to_silence']);

    if (thinkingStates.has(toState)) {
      this.isListening = false;
      if (this.onStatusChange) {
        await this.onStatusChange('thinking');
      }
    } else if (speakingStates.has(toState)) {
      this.isListening = false;
      if (this.onStatusChange) {
        await this.onStatusChange('speaking');
      }
    }
  }

  /**
   * Handle ready to listen signal from server.
   */
  async _handleReadyToListen() {
    console.log(
      `[Orchestrator] Server ready_to_listen signal received (avatarTurnActive=${this.avatarTurnActive})`
    );

    if (!this.sessionActive) return;

    if (this.avatarTurnActive) {
      console.log('[Orchestrator] Ignoring ready_to_listen - avatar turn still active (waiting for LLM)');
      return;
    }

    // Clear any accumulated transcripts and re-enable transcript processing
    this.transcriptBuffer = [];
    this._ignoreTranscripts = false;
    this._pauseAudioSending = false;
    console.log('[Orchestrator] Transcript processing re-enabled, audio sending resumed, buffer cleared');

    if (!this.isListening) {
      console.log('[Orchestrator] Enabling microphone for user input');
      this.isListening = true;
      if (this.onStatusChange) {
        await this.onStatusChange('listening');
      }
    }
  }

  /**
   * Send Finalize message to Deepgram to flush any buffered audio.
   * Only works with Nova models, not nova-3-flux.
   * See: https://developers.deepgram.com/docs/finalize
   */
  _sendDeepgramFinalize() {
    if (!this.dgConnection) {
      console.log('[Orchestrator] No Deepgram connection, skipping Finalize');
      return;
    }

    try {
      // Send Finalize control message
      this.dgConnection.finalize();
      console.log('[Orchestrator] Sent Finalize message to Deepgram');
    } catch (e) {
      console.warn('[Orchestrator] Failed to send Finalize to Deepgram:', e.message);
    }
  }
}
