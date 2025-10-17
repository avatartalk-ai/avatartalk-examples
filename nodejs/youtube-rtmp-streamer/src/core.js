import fs from 'fs/promises';
import { randomInt } from 'crypto';
import { setTimeout as sleep } from 'timers/promises';
import { OpenAI } from 'openai';
import { config } from './config.js';
import { AvatarTalkConnector } from './avatartalk.js';
import { YouTubeCommentManager } from './youtube.js';
import { Logger } from './logger.js';

export class AvatarTalkTeacher {
  constructor(liveId, backgroundUrl = config.avatartalk_default_background_url, { logLevel = 'INFO' } = {}) {
    this.logger = new Logger(logLevel);
    this.client = new OpenAI({ apiKey: config.openai_api_key });
    this.model = config.avatartalk_model;
    this.topicsFile = config.topics_file;
    this.shutdownRequested = false;
    this.youtubeLiveId = liveId || config.youtube_live_id || null;
    this.backgroundUrl = backgroundUrl || config.avatartalk_default_background_url;
    this.remainingDurationToPlay = 10; // seconds
    this.contextHistory = [];
    this.topics = [];
    this.avatartalkConnector = new AvatarTalkConnector({ backgroundUrl: this.backgroundUrl, logger: this.logger });
    this.youtubeManager = null;
    this.promptPath = config.prompt_path;
    this.systemPrompt = '';
  }

  async initialize() {
    await this.#loadTopics();
    await this.#loadSystemPrompt();
    await this.avatartalkConnector.initialize();
    if (!config.youtube_api_key) {
      this.logger.critical('YOUTUBE_API_KEY not provided');
      throw new Error('YOUTUBE_API_KEY required');
    }
    this.youtubeManager = new YouTubeCommentManager(config.youtube_api_key, { logger: this.logger });
    await this.youtubeManager.initialize();
    await this.#setupYouTubeStream();
  }

  async #loadTopics() {
    try {
      const path = this.topicsFile;
      const buf = await fs.readFile(path, 'utf8');
      const topics = buf.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
      if (!topics.length) throw new Error(`No topics found in ${path}`);
      this.topics = topics;
      this.logger.info(`Loaded ${topics.length} topics from ${path}`);
    } catch (e) {
      this.logger.critical(`Topics file ${this.topicsFile} not found or unreadable`);
      throw e;
    }
  }

  async #loadSystemPrompt() {
    try {
      const path = this.promptPath;
      this.systemPrompt = await fs.readFile(path, 'utf8');
      this.logger.info(`Loaded system prompt from ${path}`);
    } catch (e) {
      this.logger.critical(`Prompt file ${this.promptPath} not found or unreadable`);
      throw e;
    }
  }

  async #setupYouTubeStream() {
    const mgr = this.youtubeManager;
    if (!mgr) return;
    let liveId = this.youtubeLiveId;
    if (!liveId) {
      liveId = await mgr.findLiveStream();
    }
    if (liveId) {
      await mgr.getLiveChatId(liveId);
    } else {
      this.logger.warn('No live stream found, comment integration will be limited');
    }
  }

  #createUserPrompt(topic) {
    const wc = 60 + Math.floor(Math.random() * 31); // 60–90
    return `Produce ONE continuous segment in English about: ${topic}. Aim for ~${wc} words. End with a single-sentence question to the live chat.`;
  }

  #buildMessages(userPrompt) {
    const messages = [{ role: 'system', content: this.systemPrompt }];
    // Add last 2 assistant messages for context
    for (const m of this.contextHistory.slice(-2)) messages.push(m);
    messages.push({ role: 'user', content: userPrompt });
    return messages;
  }

  async #generateSegment(topic) {
    const userPrompt = this.#createUserPrompt(topic);
    const messages = this.#buildMessages(userPrompt);
    try {
      const resp = await this.client.chat.completions.create({
        model: this.model,
        messages,
        max_tokens: 200,
        temperature: 0.8,
      });
      const segment = resp?.choices?.[0]?.message?.content?.trim?.() || '';
      if (segment) this.contextHistory.push({ role: 'assistant', content: segment });
      return segment || null;
    } catch (e) {
      this.logger.error(`OpenAI API error: ${e?.message || e}`);
      return null;
    }
  }

  #selectTopic(comments) {
    if (comments && comments.length) this.logger.info(`Retrieved ${comments.length} new comments`);
    return this.#selectTopicAsync(comments);
  }

  async #selectTopicAsync(comments) {
    if (comments && comments.length) {
      try {
        const summary = await this.youtubeManager.summarizeComments(comments);
        if (summary) return summary;
      } catch (_) {
        this.logger.warn('Falling back to random topic after summarize failure');
      }
    }
    const idx = randomInt(0, this.topics.length);
    const topic = this.topics[idx];
    this.logger.info(`No new comments, using topic: ${topic}`);
    return topic;
  }

  async #playSegment(segment) {
    // Output to stdout as in Python version
    process.stdout.write(`${segment}\n\n`);
    await this.avatartalkConnector.send(segment);
    this.logger.debug('Waiting for response from AvatarTalk API...');
    const audioInfo = await this.avatartalkConnector.receive();
    const duration = parseFloat(audioInfo?.audio_duration ?? 0) || 0;
    this.logger.info(`Segment duration: ${duration.toFixed(2)}s`);
    return duration;
  }

  async run() {
    this.logger.info(`AvatarTalk Teacher starting with model: ${this.model}`);
    this.logger.info('Press Ctrl+C to stop');
    if (this.youtubeManager) this.logger.info('YouTube comment integration: ENABLED');

    let cooldownRemaining = 0;
    while (!this.shutdownRequested) {
      if (cooldownRemaining >= this.remainingDurationToPlay) {
        await sleep(1000);
        cooldownRemaining -= 1;
        continue;
      }
      try {
        const startCommentProcessing = Date.now();
        const comments = await this.youtubeManager.getRecentComments();
        const topic = await this.#selectTopicAsync(comments);

        const segment = await this.#generateSegment(topic);

        // Send message to chat if there were comments
        if (comments && comments.length > 0) {
          await this.youtubeManager.sendChatMessage(segment);
        }

        const textGenDuration = (Date.now() - startCommentProcessing) / 1000;
        if (!segment) {
          this.logger.warn('Segment generation failed; retrying soon...');
          await sleep(3000);
          continue;
        }

        const startVideoRequest = Date.now();
        const duration = await this.#playSegment(segment);
        const delay = duration - textGenDuration - ((Date.now() - startVideoRequest) / 1000);
        cooldownRemaining += delay;
      } catch (e) {
        this.logger.error(`Unexpected error: ${e?.message || e}`);
        break;
      }
    }
  }
}

