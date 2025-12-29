#!/usr/bin/env node
import yargs from 'yargs';
import { hideBin } from 'yargs/helpers';
import { AvatarTalkTeacher } from './core.js';

function parseArgs(argv) {
  const y = yargs(hideBin(argv))
    .scriptName('avatartalk-youtube-rtmp')
    .usage('$0 [video_id] [--background-url background_url]')
    .positional('video_id', { type: 'string', describe: 'YouTube Live video ID. Falls back to $YOUTUBE_LIVE_ID if omitted.' })
    .options({
      'log-level': {
        alias: 'log-level',
        type: 'string',
        default: 'INFO',
        choices: ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        describe: 'Logging verbosity (default: INFO)',
      },
      'background-url': {
        alias: 'background_url',
        type: 'string',
        default: null,
        describe: 'URL to the image that will be the background of the video'
      }
    })
    .help(false)
    .version(false)
    .strict(false);
  const parsed = y.parseSync();
  return { videoId: parsed._[0] || parsed.video_id || null, backgroundUrl: parsed['background-url'] || null, logLevel: parsed['log-level'] };
}

async function main(argv) {
  const { videoId, backgroundUrl, logLevel } = parseArgs(argv);
  const vid = videoId || process.env.YOUTUBE_LIVE_ID;
  if (!vid) {
    console.error('Error: no video ID provided. Pass it as an argument or set $YOUTUBE_LIVE_ID.');
    process.exitCode = 2;
    return;
  }

  const teacher = new AvatarTalkTeacher(vid, backgroundUrl, { logLevel });
  let shuttingDown = false;
  const onSigint = () => {
    if (shuttingDown) return;
    shuttingDown = true;
    teacher.shutdownRequested = true;
    console.error('Stopping AvatarTalk Teacher...');
    setTimeout(() => process.exit(0), 250).unref?.();
  };
  process.once('SIGINT', onSigint);

  try {
    await teacher.initialize();
    await teacher.run();
  } catch (e) {
    console.error(e?.stack || e?.message || String(e));
    process.exitCode = 1;
  }
}

main(process.argv);

