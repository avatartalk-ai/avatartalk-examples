import axios from 'axios';
import { OpenAI } from 'openai';
import { config } from './config.js';
import { Logger } from './logger.js';

export class YouTubeCommentManager {
  constructor(apiKey, { logger = new Logger('INFO') } = {}) {
    this.apiKey = apiKey;
    this.baseUrl = 'https://www.googleapis.com/youtube/v3';
    this.liveChatId = null;
    this.nextPageToken = null;
    this.lastCheckTime = new Date();
    this.logger = logger;
    this.openai = new OpenAI({ apiKey: config.openai_api_key });
    this.model = config.avatartalk_model;
    this.systemPrompt = 'You are a helpful assistant that summarizes YouTube Live chat comments. Summarize the comments in a single sentence.';
  }

  async findLiveStream(channelName = 'avatartalk') {
    try {
      const channelId = await this.#getChannelId(channelName);
      if (!channelId) {
        this.logger.warn(`Channel ${channelName} not found`);
        return null;
      }
      const params = {
        part: 'snippet',
        channelId,
        type: 'video',
        eventType: 'live',
        key: this.apiKey,
      };
      const { data } = await axios.get(`${this.baseUrl}/search`, { params, timeout: 10000 });
      if (data?.items?.length) {
        const videoId = data.items[0]?.id?.videoId;
        this.logger.info(`Found live stream: ${videoId}`);
        return videoId || null;
      }
      this.logger.info('No live stream found');
      return null;
    } catch (e) {
      this.logger.error(`Error finding live stream: ${e?.message || e}`);
      return null;
    }
  }

  async #getChannelId(channelName) {
    try {
      const params = { part: 'snippet', q: channelName, type: 'channel', key: this.apiKey };
      const { data } = await axios.get(`${this.baseUrl}/search`, { params, timeout: 10000 });
      if (data?.items?.length) return data.items[0]?.id?.channelId || null;
      return null;
    } catch (e) {
      this.logger.error(`Error getting channel ID: ${e?.message || e}`);
      return null;
    }
  }

  async getLiveChatId(videoId) {
    try {
      const params = { part: 'snippet,liveStreamingDetails', id: videoId, key: this.apiKey };
      const { data } = await axios.get(`${this.baseUrl}/videos`, { params, timeout: 10000 });
      const live = data?.items?.[0]?.liveStreamingDetails;
      const liveChatId = live?.activeLiveChatId || null;
      if (!liveChatId) throw new Error('Live chat ID not found');
      this.liveChatId = liveChatId;
      this.logger.info(`Live chat ID: ${liveChatId}`);
      return liveChatId;
    } catch (e) {
      this.logger.error(`Error getting live chat ID: ${e?.message || e}`);
      return null;
    }
  }

  async getRecentComments() {
    if (!this.liveChatId) return [];
    try {
      const params = {
        liveChatId: this.liveChatId,
        part: 'snippet,authorDetails',
        key: this.apiKey,
      };
      if (this.nextPageToken) params.pageToken = this.nextPageToken;

      const { data } = await axios.get(`${this.baseUrl}/liveChat/messages`, { params, timeout: 10000 });
      this.nextPageToken = data?.nextPageToken || null;

      const comments = [];
      const currentTime = new Date();

      for (const item of data?.items || []) {
        const snippet = item?.snippet || {};
        const author = item?.authorDetails || {};
        const publishedAt = new Date(snippet?.publishedAt || 0);
        if (publishedAt > this.lastCheckTime) {
          const details = snippet?.textMessageDetails || {};
          const text = details?.messageText || '';
          comments.push({
            text,
            author: author?.displayName || '',
            timestamp: publishedAt,
            is_moderator: !!author?.isChatModerator,
            is_owner: !!author?.isChatOwner,
          });
        }
      }
      this.lastCheckTime = currentTime;
      return comments;
    } catch (e) {
      this.logger.error(`Error getting comments: ${e?.message || e}`);
      return [];
    }
  }

  async summarizeComments(comments) {
    const messages = [
      { role: 'system', content: this.systemPrompt },
      { role: 'user', content: comments.map((c) => `${c.author}: ${c.text}`).join('\n') },
    ];
    try {
      const resp = await this.openai.chat.completions.create({
        model: this.model,
        messages,
        max_tokens: 200,
        temperature: 0.8,
      });
      return resp?.choices?.[0]?.message?.content?.trim?.() || '';
    } catch (e) {
      this.logger.error(`OpenAI API error: ${e?.message || e}`);
      throw e;
    }
  }
}

