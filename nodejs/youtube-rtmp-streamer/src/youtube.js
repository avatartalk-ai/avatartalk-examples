import axios from 'axios';
import { google } from 'googleapis';
import { OpenAI } from 'openai';
import { config } from './config.js';
import { Logger } from './logger.js';
import natural from 'natural';
import fs from 'fs';

const { SentenceTokenizer } = natural;

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
    this.youtube = null;
    this.secretsPath = config.google_client_secrets_path;
    this.tokenizer = new SentenceTokenizer();
  }

  async initialize() {
    if (!this.secretsPath) {
      throw new Error('GOOGLE_CLIENT_SECRETS_PATH not set!');
    }

    const SCOPES = ['https://www.googleapis.com/auth/youtube', 'https://www.googleapis.com/auth/youtube.force-ssl'];

    const credentials = JSON.parse(fs.readFileSync(this.secretsPath, 'utf8'));

    // Start local server and get auth code
    const { code, oauth2Client } = await this.#runLocalServer(credentials, SCOPES);
    const { tokens } = await oauth2Client.getToken(code);
    oauth2Client.setCredentials(tokens);

    this.youtube = google.youtube({ version: 'v3', auth: oauth2Client });
    this.logger.info('OAuth2 authorization successful');
  }

  async #runLocalServer(credentials, scopes) {
    const http = await import('http');
    const { parse } = await import('url');
    const { exec } = await import('child_process');
    const { promisify } = await import('util');
    const execAsync = promisify(exec);

    return new Promise((resolve, reject) => {
      let oauth2Client;

      const server = http.createServer(async (req, res) => {
        try {
          const url = parse(req.url, true);
          if (url.pathname === '/') {
            const code = url.query.code;
            if (code) {
              res.writeHead(200, { 'Content-Type': 'text/html' });
              res.end('<h1>Authorization successful!</h1><p>You can close this window and return to the application.</p>');
              server.close();
              resolve({ code, oauth2Client });
            } else {
              res.writeHead(400, { 'Content-Type': 'text/html' });
              res.end('<h1>Authorization failed!</h1><p>No code received.</p>');
              server.close();
              reject(new Error('No authorization code received'));
            }
          }
        } catch (e) {
          reject(e);
        }
      });

      server.listen(0, async () => {
        const port = server.address().port;
        const redirectUrl = `http://localhost:${port}`;

        // Create OAuth2 client with the actual port
        oauth2Client = new google.auth.OAuth2(
          credentials.installed.client_id,
          credentials.installed.client_secret,
          redirectUrl
        );

        const authUrl = oauth2Client.generateAuthUrl({
          access_type: 'offline',
          scope: scopes,
        });

        this.logger.info('Please visit this URL to authorize the application:');
        this.logger.info(authUrl);
        this.logger.info('');

        // Try to open the browser automatically
        try {
          const platform = process.platform;
          if (platform === 'darwin') {
            await execAsync(`open "${authUrl}"`);
          } else if (platform === 'win32') {
            await execAsync(`start "${authUrl}"`);
          } else {
            await execAsync(`xdg-open "${authUrl}"`);
          }
        } catch (e) {
          this.logger.warn('Could not open browser automatically. Please visit the URL above manually.');
        }
      });
    });
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
        if (publishedAt > this.lastCheckTime && !author?.isChatOwner) {
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

  async sendChatMessage(message) {
    if (!this.youtube || !this.liveChatId) {
      this.logger.warn('Cannot send message: YouTube client or liveChatId not initialized');
      return null;
    }

    try {
      for (const msgChunk of this.splitIntoChunks(message)) {
        await this.youtube.liveChatMessages.insert({
          part: ['snippet'],
          requestBody: {
            snippet: {
              liveChatId: this.liveChatId,
              type: 'textMessageEvent',
              textMessageDetails: {
                messageText: msgChunk,
              },
            },
          },
        });
        // Wait 1 second between messages to avoid rate limiting
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      this.logger.info('Message sent successfully!');
      return true;
    } catch (e) {
      this.logger.error(`Error sending chat message: ${e?.message || e}`);
      return null;
    }
  }

  *splitIntoChunks(text, maxCharacters = 200) {
    const sentences = this.tokenizer.tokenize(text);
    let currentChunk = '';

    for (const sentence of sentences) {
      if ((currentChunk + ' ' + sentence).length < maxCharacters) {
        currentChunk = currentChunk ? currentChunk + ' ' + sentence : sentence;
      } else {
        if (currentChunk) yield currentChunk.trim();
        currentChunk = sentence;
      }
    }

    if (currentChunk) yield currentChunk.trim();
  }
}

