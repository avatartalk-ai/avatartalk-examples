import fs from 'fs/promises';
import { setTimeout as sleep } from 'timers/promises';
import { OpenAI } from 'openai';
import { config } from './config.js';
import { AvatarTalkConnector } from './avatartalk.js';
import { YouTubeCommentManager } from './youtube.js';
import { Logger } from './logger.js';

const THEME_DOMAINS = [
  'Workplace & leadership situations (pushing back on deadlines, giving tough feedback, running crisp meetings, salary & career talks)',
  "Everyday social life & travel (hotels, airports, restaurants, making friends abroad, small talk that isn't boring, graceful exits)",
  'Sales, client relations & negotiations (handling objections, building trust, following up without being annoying, setting boundaries)',
  'Idioms, phrasal verbs & colorful native expressions people use in daily conversation',
  'Cultural & tone nuances (British vs American understatement, sounding polite vs passive-aggressive, softening direct requests)',
  'Modern digital communication (Slack, emails, voice notes, video calls — sounding warm and sharp instead of stiff or robotic)',
  'Pronunciation, word stress & rhythm secrets that instantly make spoken English sound more natural',
  'Storytelling, humor, and thinking on your feet when you get an unexpected question',
];

const ARC_STEPS = [
  'Part 1 of 4 (Introduce the Theme): Open a new mini-chapter. Set up a relatable real-life situation for this theme and teach the first natural phrase or core insight.',
  'Part 2 of 4 (Common Mistake vs Upgrade): Stay on the EXACT same theme! Contrast a stiff, textbook, or awkward phrase people often use in this situation with what fluent speakers actually say.',
  'Part 3 of 4 (Nuance, Mini-Dialogue, or Idiom): Stay on the EXACT same theme! Go one layer deeper—share a vivid mini-example, a tone nuance, or a great idiom that fits this exact situation.',
  'Part 4 of 4 (Wrap-Up & Audience Question): Conclude this mini-chapter with a final practical takeaway and ask a natural question inviting viewers in the live chat to share how they handle it.',
];

export class AvatarTalkTeacher {
  constructor(liveId, backgroundUrl = config.avatartalk_default_background_url, { logLevel = 'INFO' } = {}) {
    this.logger = new Logger(logLevel);
    this.client = new OpenAI({ apiKey: config.openai_api_key });
    this.model = config.avatartalk_model;
    this.shutdownRequested = false;
    this.youtubeLiveId = liveId || config.youtube_live_id || null;
    this.backgroundUrl = backgroundUrl || config.avatartalk_default_background_url;
    this.contextHistory = [];
    this.coveredTopics = [];
    this.segmentCounter = 0;
    this.arcStep = 0;
    this.themeIndex = 0;
    this.currentTheme = null;
    this.avatartalkConnector = new AvatarTalkConnector({ backgroundUrl: this.backgroundUrl, logger: this.logger });
    this.youtubeManager = null;
    this.promptPath = config.prompt_path;
    this.systemPrompt = '';
  }

  async initialize() {
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

  #createUserPrompt(chatTopicHint = null) {
    const wc = 28 + Math.floor(Math.random() * 9); // 28–36
    const includeCta = this.segmentCounter % 8 === 7;
    this.segmentCounter += 1;

    const coveredBlock = this.coveredTopics.length
      ? `Previously covered themes & sub-points (DO NOT repeat any of these concepts, words, idioms, or scenarios):\n- ${this.coveredTopics.slice(-80).join('\n- ')}`
      : 'No topics covered yet in this session.';

    const ctaInstruction = includeCta
      ? 'At the end of this segment, casually mention that viewers can practice 1-on-1 live voice role-play at avatartalk.ai/ai-training.'
      : 'Do NOT mention avatartalk.ai in this segment; focus 100% on the conversation and language insight.';

    let focusInstruction;
    if (chatTopicHint) {
      this.currentTheme = `Viewer chat topic: ${chatTopicHint}`;
      this.arcStep = 1;
      focusInstruction = `Viewers in the live chat just brought up: ${chatTopicHint}.\nMake this our current theme! Respond to it warmly and teach a practical English insight around it.`;
    } else if (this.arcStep === 0 || !this.currentTheme) {
      const domain = THEME_DOMAINS[this.themeIndex % THEME_DOMAINS.length];
      this.themeIndex += 1;
      const stepInstruction = ARC_STEPS[0];
      this.arcStep = 1;
      focusInstruction = `Domain for this new 4-part mini-chapter: ${domain}\n${stepInstruction}\nChoose a specific, fresh overarching 'theme' in English that is NOT in the previously covered list. If you were talking about something else right before this, use a smooth 3–5 word bridge into this new theme.`;
    } else {
      const stepInstruction = ARC_STEPS[this.arcStep];
      this.arcStep = (this.arcStep + 1) % ARC_STEPS.length;
      focusInstruction = `Current overarching theme (STAY ON THIS THEME): ${this.currentTheme}\n${stepInstruction}\nConnect naturally to what you just said in the previous segment so it feels like one continuous, thoughtful explanation.`;
    }

    return (
      `${coveredBlock}\n\n` +
      `${focusInstruction}\n` +
      `${ctaInstruction}\n` +
      `Target length for 'segment': ~${wc} words (2–3 natural sentences in English).\n` +
      'Return JSON: {"theme": "<current overarching theme>", "topic": "<specific 5-10 word sub-point taught in this segment>", "segment": "<spoken text>"}'
    );
  }

  #buildMessages(userPrompt) {
    const messages = [{ role: 'system', content: this.systemPrompt }];
    // Add last 8 assistant messages for continuity and stylistic variety
    for (const m of this.contextHistory.slice(-8)) messages.push(m);
    messages.push({ role: 'user', content: userPrompt });
    return messages;
  }

  async #generateSegment(chatTopicHint = null) {
    const userPrompt = this.#createUserPrompt(chatTopicHint);
    const messages = this.#buildMessages(userPrompt);
    try {
      const resp = await this.client.chat.completions.create({
        model: this.model,
        messages,
        max_tokens: 200,
        temperature: 0.85,
        response_format: { type: 'json_object' },
      });
      const rawContent = resp?.choices?.[0]?.message?.content?.trim?.() || '';
      let themeName = '';
      let topicSummary = '';
      let segment = rawContent;
      try {
        const parsed = JSON.parse(rawContent);
        if (parsed && typeof parsed === 'object') {
          themeName = String(parsed.theme || '').trim();
          topicSummary = String(parsed.topic || '').trim();
          segment = String(parsed.segment || '').trim();
        }
      } catch (_) {
        this.logger.warn('Model did not return valid JSON; using raw content as segment');
      }
      if (!segment) return null;
      if (themeName) this.currentTheme = themeName;
      const entry = topicSummary
        ? (this.currentTheme ? `${this.currentTheme} — ${topicSummary}` : topicSummary)
        : segment.slice(0, 60);
      this.coveredTopics.push(entry);
      if (this.coveredTopics.length > 150) this.coveredTopics.shift();
      this.contextHistory.push({ role: 'assistant', content: segment });
      if (this.contextHistory.length > 8) this.contextHistory.shift();
      if (topicSummary) {
        this.logger.info(`Agent segment (#${this.segmentCounter}, memory=${this.coveredTopics.length}): [${this.currentTheme || 'general'}] ${topicSummary}`);
      }
      return segment;
    } catch (e) {
      this.logger.error(`OpenAI API error: ${e?.message || e}`);
      return null;
    }
  }

  async #summarizeChatHint(comments) {
    if (comments && comments.length) {
      try {
        const summary = await this.youtubeManager.summarizeComments(comments);
        if (summary) return summary;
      } catch (_) {
        this.logger.warn('Failed to summarize chat; agent will select topic autonomously');
      }
    }
    return null;
  }

  async #playSegment(segment) {
    await this.avatartalkConnector.send(segment);
    this.logger.debug('Waiting for response from AvatarTalk API...');
    const audioInfo = await this.avatartalkConnector.receive();
    const duration = parseFloat(audioInfo?.audio_duration ?? 0) || 0;
    // Output to stdout as playback starts
    process.stdout.write(`${segment}\n\n`);
    this.logger.info(`Segment duration: ${duration.toFixed(2)}s`);
    return duration;
  }

  async run() {
    this.logger.info(`AvatarTalk Teacher starting with model: ${this.model}`);
    this.logger.info('Press Ctrl+C to stop');
    if (this.youtubeManager) this.logger.info('YouTube comment integration: ENABLED');

    let playbackEndsAt = Date.now() / 1000;
    const generationLeadSeconds = 5.0;
    const sendLeadSeconds = 1.8;
    const firstChunkStartupOffset = 3.5;

    while (!this.shutdownRequested) {
      const now = Date.now() / 1000;
      const remaining = Math.max(0, playbackEndsAt - now);
      if (remaining > generationLeadSeconds) {
        await sleep(Math.min(1000, (remaining - generationLeadSeconds) * 1000));
        continue;
      }
      try {
        const comments = await this.youtubeManager.getRecentComments();
        const chatHint = await this.#summarizeChatHint(comments);

        const segment = await this.#generateSegment(chatHint);

        // Send message to chat if there were comments
        if (comments && comments.length > 0 && segment) {
          await this.youtubeManager.sendChatMessage(segment);
        }

        if (!segment) {
          this.logger.warn('Segment generation failed; retrying soon...');
          await sleep(3000);
          continue;
        }

        while (!this.shutdownRequested) {
          const rem = playbackEndsAt - Date.now() / 1000;
          if (rem <= sendLeadSeconds) break;
          await sleep(Math.min(500, (rem - sendLeadSeconds) * 1000));
        }
        if (this.shutdownRequested) break;

        const duration = await this.#playSegment(segment);
        const nowAfterSend = Date.now() / 1000;
        if (this.avatartalkConnector.firstChunkOnWs) {
          this.avatartalkConnector.firstChunkOnWs = false;
          playbackEndsAt = Math.max(nowAfterSend, playbackEndsAt) + duration + firstChunkStartupOffset;
        } else {
          playbackEndsAt = Math.max(nowAfterSend, playbackEndsAt) + duration;
        }
      } catch (e) {
        this.logger.error(`Unexpected error: ${e?.message || e}`);
        break;
      }
    }
  }
}

