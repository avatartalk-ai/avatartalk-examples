const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const floatingStopBtn = document.getElementById('floatingStopBtn');
const mobileToggleBtn = document.getElementById('mobileToggleBtn');
const sidebarCollapseBtn = document.getElementById('sidebarCollapseBtn');
const avatarVideo = document.getElementById('avatarVideo');
const statusBadge = document.getElementById('statusBadge');
const micIndicator = document.getElementById('micIndicator');
const micStatus = document.getElementById('micStatus');
const avatarSelect = document.getElementById('avatarName');
const usePregenCheckbox = document.getElementById('usePregen');
const usePregenWrapper = document.getElementById('usePregenWrapper');
const languageSelect = document.getElementById('language');

let ws = null;  // Single unified WebSocket for control + video
let mediaSource = null;
let sourceBuffer = null;
let segmentQueue = [];
let audioContext = null;
let audioWorklet = null;
let mediaStream = null;
let bufferMonitorInterval = null;
let playbackWatchdogInterval = null;  // Watchdog to detect stalled playback
let lastPlaybackTime = 0;  // Track last known playback position
let stallRecoveryAttempts = 0;  // Count recovery attempts to avoid infinite loops
let pendingStatusTimeouts = [];  // Track pending status change timeouts
let isSessionActive = false;  // Track if session is active

// Constants for playback monitoring
const WATCHDOG_INTERVAL_MS = 500;  // Check playback every 500ms
const MAX_STALL_RECOVERY_ATTEMPTS = 5;  // Max recovery attempts before giving up
const STALL_THRESHOLD_MS = 1000;  // Consider stalled if no progress for 1 second

// Configuration
const ROOT_PATH = window.ROOT_PATH || '';
const SERVER_URL = window.location.protocol + '//' + window.location.host + ROOT_PATH;
const WS_URL = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + ROOT_PATH + '/ws/conversation';

// Fetch and populate language options from backend
async function loadLanguages() {
    try {
        const response = await fetch(`${SERVER_URL}/api/languages`);
        if (!response.ok) {
            console.error('Failed to fetch languages:', response.status);
            return;
        }
        const data = await response.json();
        const languages = data.languages || [];
        const defaultLang = data.default || 'en';

        // Clear existing options and populate with fetched languages
        languageSelect.innerHTML = '';
        languages.forEach(lang => {
            const option = document.createElement('option');
            option.value = lang.code;
            option.textContent = lang.name;
            if (lang.code === defaultLang) {
                option.selected = true;
            }
            languageSelect.appendChild(option);
        });
    } catch (err) {
        console.error('Error loading languages:', err);
    }
}

// Load languages on page load
loadLanguages();

// --- UI Helpers ---
function updateUsePregenVisibility() {
    if (!avatarSelect || !usePregenWrapper || !usePregenCheckbox) {
        return;
    }
    const isMexicanWoman = avatarSelect.value === 'mexican_woman';
    usePregenWrapper.style.display = isMexicanWoman ? 'flex' : 'none';
    if (!isMexicanWoman) {
        usePregenCheckbox.checked = false;
    }
}

function getUsePregenPreference() {
    if (!avatarSelect || !usePregenCheckbox) {
        return false;
    }
    return avatarSelect.value === 'mexican_woman' && usePregenCheckbox.checked;
}

if (avatarSelect) {
    avatarSelect.addEventListener('change', updateUsePregenVisibility);
    updateUsePregenVisibility();
}

function setMicState(isOn) {
    micIndicator.style.display = 'flex';
    if (isOn) {
        micIndicator.classList.remove('mic-off');
        micIndicator.classList.add('mic-on');
        micStatus.textContent = 'On';
        resumeAudioCapture();
    } else {
        micIndicator.classList.remove('mic-on');
        micIndicator.classList.add('mic-off');
        micStatus.textContent = 'Off';
        pauseAudioCapture();
    }
}

function applyStatusImmediate(status) {
    // Apply status change immediately (no buffer delay)
    statusBadge.style.display = 'block';
    statusBadge.className = 'status-badge';

    if (status === 'listening') {
        statusBadge.textContent = 'Listening';
        statusBadge.classList.add('status-listening');
        setMicState(true);
    } else if (status === 'thinking') {
        statusBadge.textContent = 'Thinking...';
        statusBadge.classList.add('status-thinking');
        setMicState(false);
    } else if (status === 'speaking') {
        statusBadge.textContent = 'Speaking';
        statusBadge.classList.add('status-speaking');
        setMicState(false);
    } else {
        statusBadge.textContent = status;
    }
}

function getVideoBufferDelayMs() {
    // Calculate how much video is buffered ahead of current playback
    // Handles multiple buffer ranges (gaps) which Chrome is sensitive to
    if (!avatarVideo.buffered || avatarVideo.buffered.length === 0) {
        return 0;
    }

    const currentTime = avatarVideo.currentTime || 0;

    // Find the buffer range that contains the current playback position
    for (let i = 0; i < avatarVideo.buffered.length; i++) {
        const start = avatarVideo.buffered.start(i);
        const end = avatarVideo.buffered.end(i);

        // Current time is within this range or just before it
        if (currentTime >= start - 0.1 && currentTime <= end) {
            return Math.max(0, (end - currentTime) * 1000);
        }
    }

    // Current time is not in any buffered range - may indicate a gap/stall
    // Return 0 to indicate no usable buffer ahead
    return 0;
}

function setStatus(status, syncWithBuffer = true) {
    // Cancel any pending status changes to avoid out-of-order updates
    pendingStatusTimeouts.forEach(t => clearTimeout(t));
    pendingStatusTimeouts = [];

    if (!syncWithBuffer) {
        // Apply immediately (e.g., for initial 'thinking' on EOT)
        applyStatusImmediate(status);
        return;
    }

    // Delay status change to sync with video playback
    const delayMs = getVideoBufferDelayMs();

    if (delayMs < 50) {
        // Buffer too small, apply immediately
        applyStatusImmediate(status);
    } else {
        console.log(`Delaying status '${status}' by ${delayMs.toFixed(0)}ms to sync with video`);
        const timeoutId = setTimeout(() => {
            applyStatusImmediate(status);
        }, delayMs);
        pendingStatusTimeouts.push(timeoutId);
    }
}

// --- Video Handling (MSE) ---
function setupMediaSource() {
    return new Promise((resolve, reject) => {
        // Timeout to prevent hanging indefinitely
        const timeoutId = setTimeout(() => {
            reject(new Error('MediaSource sourceopen timed out'));
        }, 5000);

        // Common H.264 profiles: Baseline, Main, High
        const codecs = [
            'video/mp4; codecs="avc1.42E01E, mp4a.40.2"', // Baseline Profile, Level 3.0
            'video/mp4; codecs="avc1.64001E, mp4a.40.2"', // High Profile, Level 3.0
            'video/mp4; codecs="avc1.4d401f, mp4a.40.2"', // Main Profile, Level 3.1
            'video/mp4; codecs="avc1.42001E, mp4a.40.2"', // Baseline?
        ];

        let mimeType = null;
        for (const codec of codecs) {
            if (MediaSource.isTypeSupported(codec)) {
                console.log('Using supported codec:', codec);
                mimeType = codec;
                break;
            }
        }

        if (!mimeType) {
            clearTimeout(timeoutId);
            const err = new Error('MSE type not supported for any common H.264 profile');
            console.error('MSE type not supported. Checked:', codecs);
            reject(err);
            return;
        }

        mediaSource = new MediaSource();
        avatarVideo.src = URL.createObjectURL(mediaSource);

        mediaSource.addEventListener('sourceopen', () => {
            clearTimeout(timeoutId);
            try {
                sourceBuffer = mediaSource.addSourceBuffer(mimeType);
                // Use 'sequence' mode for seamless playback across segments
                // This ignores in-stream timestamps and plays segments in append order
                // Critical for live-streaming scenarios where each segment has independent timestamps
                sourceBuffer.mode = 'sequence';
                sourceBuffer.addEventListener('updateend', pumpSegmentQueue);
                // Pump any segments that arrived while we were setting up
                pumpSegmentQueue();
                resolve();
            } catch (err) {
                console.error('Error creating source buffer:', err);
                reject(err);
            }
        }, { once: true });
    });
}

function pumpSegmentQueue() {
    if (!sourceBuffer || !mediaSource) return;
    if (mediaSource.readyState !== 'open') return;
    if (sourceBuffer.updating) return;
    if (segmentQueue.length === 0) return;

    const segment = segmentQueue.shift();
    try {
        sourceBuffer.appendBuffer(segment);
    } catch (err) {
        console.error('Error appending video data:', err);
    }
}

function startBufferMonitoring() {
    if (bufferMonitorInterval) {
        clearInterval(bufferMonitorInterval);
    }

    bufferMonitorInterval = setInterval(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (!avatarVideo.buffered || avatarVideo.buffered.length === 0) return;

        const bufferedMs = getVideoBufferDelayMs();
        const currentTime = avatarVideo.currentTime || 0;

        const msg = {
            type: 'buffer_status',
            data: {
                buffered_ms: bufferedMs,
                playback_position: currentTime,
            },
        };

        try {
            ws.send(JSON.stringify(msg));
        } catch (err) {
            console.warn('Error sending buffer_status:', err);
        }
    }, 1000);
}

function stopBufferMonitoring() {
    if (bufferMonitorInterval) {
        clearInterval(bufferMonitorInterval);
        bufferMonitorInterval = null;
    }
}

// --- Gap Detection and Jumping ---
// Handles small gaps in buffered ranges that can cause micro-freezes
function setupGapJumping() {
    avatarVideo.addEventListener('timeupdate', () => {
        if (!isSessionActive) return;

        const currentTime = avatarVideo.currentTime;
        const buffered = avatarVideo.buffered;

        if (buffered.length === 0) return;

        // Check if we're approaching a gap
        for (let i = 0; i < buffered.length - 1; i++) {
            const rangeEnd = buffered.end(i);
            const nextRangeStart = buffered.start(i + 1);
            const gapSize = nextRangeStart - rangeEnd;

            // If there's a small gap (< 500ms) and we're close to it, jump over it
            if (gapSize > 0 && gapSize < 0.5 && currentTime >= rangeEnd - 0.1 && currentTime < nextRangeStart) {
                console.log(`Gap detected: ${rangeEnd.toFixed(2)}s to ${nextRangeStart.toFixed(2)}s (${(gapSize * 1000).toFixed(0)}ms), jumping over`);
                avatarVideo.currentTime = nextRangeStart + 0.01;
                return;
            }
        }
    });
}

// Initialize gap jumping
setupGapJumping();

// --- Playback Watchdog (Cross-browser stall detection) ---
function startPlaybackWatchdog() {
    if (playbackWatchdogInterval) {
        clearInterval(playbackWatchdogInterval);
    }

    lastPlaybackTime = avatarVideo.currentTime;
    stallRecoveryAttempts = 0;

    playbackWatchdogInterval = setInterval(() => {
        if (!isSessionActive) return;

        const currentTime = avatarVideo.currentTime;
        const hasBuffer = getVideoBufferDelayMs() > 100;  // At least 100ms buffered
        const isPaused = avatarVideo.paused;
        const isEnded = avatarVideo.ended;
        const readyState = avatarVideo.readyState;

        // Check if playback should be happening but isn't
        // readyState >= 2 (HAVE_CURRENT_DATA) means we have data to play
        if (!isPaused && !isEnded && hasBuffer && readyState >= 2) {
            // Video should be playing - check if currentTime is advancing
            if (Math.abs(currentTime - lastPlaybackTime) < 0.01) {
                // currentTime hasn't moved - potential stall
                console.warn(`Playback watchdog: Detected stall at ${currentTime.toFixed(2)}s (readyState=${readyState}, buffer=${getVideoBufferDelayMs().toFixed(0)}ms)`);
                attemptStallRecovery();
            }
        }

        lastPlaybackTime = currentTime;
    }, WATCHDOG_INTERVAL_MS);
}

function stopPlaybackWatchdog() {
    if (playbackWatchdogInterval) {
        clearInterval(playbackWatchdogInterval);
        playbackWatchdogInterval = null;
    }
}

function attemptStallRecovery() {
    if (stallRecoveryAttempts >= MAX_STALL_RECOVERY_ATTEMPTS) {
        console.error('Max stall recovery attempts reached, giving up');
        return;
    }

    stallRecoveryAttempts++;
    console.log(`Attempting stall recovery (attempt ${stallRecoveryAttempts}/${MAX_STALL_RECOVERY_ATTEMPTS})`);

    // Try multiple recovery strategies
    if (avatarVideo.paused) {
        // If somehow paused, try to resume
        avatarVideo.play().catch(e => console.warn('Recovery play() failed:', e));
    } else {
        // Force a micro-seek to unstick the decoder
        // This is a common technique used by professional video players
        const currentTime = avatarVideo.currentTime;
        const bufferedMs = getVideoBufferDelayMs();

        if (bufferedMs > 100) {
            // Seek forward slightly within the buffer
            const seekTarget = Math.min(currentTime + 0.1, avatarVideo.buffered.end(findCurrentBufferIndex()));
            avatarVideo.currentTime = seekTarget;
            console.log(`Micro-seek recovery: ${currentTime.toFixed(2)}s -> ${seekTarget.toFixed(2)}s`);
        }

        // Also try play() in case it helps
        avatarVideo.play().catch(e => console.warn('Recovery play() failed:', e));
    }
}

function findCurrentBufferIndex() {
    const currentTime = avatarVideo.currentTime;
    for (let i = 0; i < avatarVideo.buffered.length; i++) {
        if (currentTime >= avatarVideo.buffered.start(i) - 0.1 &&
            currentTime <= avatarVideo.buffered.end(i)) {
            return i;
        }
    }
    return 0;
}

// --- Video Event Handlers (Cross-browser stall detection) ---
function setupVideoEventHandlers() {
    // Handle 'waiting' event - fired when playback stops due to lack of data
    avatarVideo.addEventListener('waiting', () => {
        if (!isSessionActive) return;
        console.log('Video waiting event - playback stalled, waiting for data');
    });

    // Handle 'stalled' event - fired when browser is trying to fetch but not receiving data
    avatarVideo.addEventListener('stalled', () => {
        if (!isSessionActive) return;
        console.log('Video stalled event - network stall detected');
    });

    // Handle 'playing' event - fired when playback resumes after pause/stall
    avatarVideo.addEventListener('playing', () => {
        if (!isSessionActive) return;
        console.log('Video playing event - playback resumed');
        // Reset stall recovery counter on successful playback
        stallRecoveryAttempts = 0;
    });

    // Handle 'pause' event - detect unexpected pauses
    avatarVideo.addEventListener('pause', () => {
        if (!isSessionActive) return;

        // Check if this was an unexpected pause (not user-initiated or session-end)
        const hasBuffer = getVideoBufferDelayMs() > 100;
        if (hasBuffer && isSessionActive) {
            console.warn('Unexpected pause detected with buffer available, attempting recovery');
            setTimeout(() => {
                if (isSessionActive && avatarVideo.paused && !avatarVideo.ended) {
                    avatarVideo.play().catch(e => console.warn('Pause recovery play() failed:', e));
                }
            }, 100);
        }
    });

    // Handle 'error' event
    avatarVideo.addEventListener('error', (e) => {
        console.error('Video error:', avatarVideo.error);
    });
}

// Initialize video event handlers once
setupVideoEventHandlers();

// Video data is now received as binary frames on the unified WebSocket
// No separate video connection needed

// --- Audio Capture ---
let isAudioPaused = false;

async function startAudioCapture() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });

        // Create AudioContext at 16kHz if possible to save bandwidth/resampling
        audioContext = new (window.AudioContext || window.webkitAudioContext)();

        // Inform backend about the actual audio sample rate so it can configure Deepgram
        if (ws && ws.readyState === WebSocket.OPEN) {
            try {
                ws.send(JSON.stringify({
                    type: 'audio_config',
                    data: {
                        sample_rate: audioContext.sampleRate,
                        channel_count: 1,
                    }
                }));
            } catch (err) {
                console.warn('Failed to send audio config:', err);
            }
        }

        await audioContext.audioWorklet.addModule(URL.createObjectURL(new Blob([`
            class AudioProcessor extends AudioWorkletProcessor {
                constructor() {
                    super();
                    // Target ~80ms chunks as recommended by Deepgram Flux
                    this.targetSamples = Math.round(sampleRate * 0.08);
                    if (!Number.isFinite(this.targetSamples) || this.targetSamples <= 0) {
                        // Fallback to a reasonable default
                        this.targetSamples = 128;
                    }
                    this.buffer = new Int16Array(this.targetSamples);
                    this.offset = 0;
                }

                process(inputs, outputs, parameters) {
                    const input = inputs[0];
                    if (input.length > 0) {
                        const channelData = input[0]; // Float32Array
                        for (let i = 0; i < channelData.length; i++) {
                            // Clamp and scale float [-1, 1] to Int16
                            const s = Math.max(-1, Math.min(1, channelData[i]));
                            const v = s < 0 ? s * 0x8000 : s * 0x7FFF;
                            this.buffer[this.offset++] = v;

                            if (this.offset >= this.targetSamples) {
                                // Copy out a full chunk and send to main thread
                                const chunk = this.buffer.slice(0, this.targetSamples);
                                this.port.postMessage(chunk.buffer, [chunk.buffer]);
                                this.offset = 0;
                            }
                        }
                    }
                    return true;
                }
            }
            registerProcessor('audio-processor', AudioProcessor);
        `], { type: 'application/javascript' })));

        const source = audioContext.createMediaStreamSource(mediaStream);
        audioWorklet = new AudioWorkletNode(audioContext, 'audio-processor');

        audioWorklet.port.onmessage = (event) => {
            if (!isAudioPaused && ws && ws.readyState === WebSocket.OPEN) {
                ws.send(event.data);
            }
        };

        source.connect(audioWorklet);
        // Note: AudioWorklet doesn't need to connect to destination unless we want monitoring

        console.log("Audio capture started");

    } catch (err) {
        console.error("Error starting audio capture:", err);
        alert("Could not access microphone. Please ensure you have granted permission.");
    }
}

function stopAudioCapture() {
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
}

function pauseAudioCapture() {
    isAudioPaused = true;
}

function resumeAudioCapture() {
    isAudioPaused = false;
}


// --- Main Control ---

// Check if we're on mobile viewport
function isMobileViewport() {
    return window.matchMedia('(max-width: 768px)').matches;
}

// Toggle sidebar collapsed state (mobile only)
function toggleSidebar() {
    document.body.classList.toggle('sidebar-collapsed');
}

// Wire up mobile toggle button (hamburger - expands sidebar)
if (mobileToggleBtn) {
    mobileToggleBtn.onclick = toggleSidebar;
}

// Wire up sidebar collapse button (inside sidebar - collapses it)
if (sidebarCollapseBtn) {
    sidebarCollapseBtn.onclick = toggleSidebar;
}

startBtn.onclick = async () => {
    startBtn.disabled = true;
    isSessionActive = true;
    stallRecoveryAttempts = 0;

    // Enable mobile full-screen mode (collapse sidebar on mobile)
    document.body.classList.add('session-active');
    if (isMobileViewport()) {
        document.body.classList.add('sidebar-collapsed');
    }

    // Connect to unified WebSocket (handles both control messages and video)
    ws = new WebSocket(WS_URL);
    ws.binaryType = 'arraybuffer';  // Receive video as ArrayBuffer

    ws.onopen = async () => {
        console.log("Unified WebSocket connected");

        // Setup MediaSource for video playback BEFORE sending init
        try {
            await setupMediaSource();
        } catch (e) {
            console.error("Video setup failed (continuing with audio only):", e);
            const container = document.querySelector('.video-container');
            const errorMsg = document.createElement('div');
            errorMsg.style.position = 'absolute';
            errorMsg.style.top = '50%';
            errorMsg.style.left = '50%';
            errorMsg.style.transform = 'translate(-50%, -50%)';
            errorMsg.style.color = 'white';
            errorMsg.style.textAlign = 'center';
            errorMsg.innerHTML = 'Video format not supported<br>Audio only mode';
            container.appendChild(errorMsg);
        }

        // Send init config
        const config = {
            type: 'init',
            data: {
                avatar: document.getElementById('avatarName').value,
                expression: document.getElementById('expression').value,
                prompt: document.getElementById('systemPrompt').value,
                language: languageSelect.value,
                use_pregen: getUsePregenPreference()
            }
        };
        ws.send(JSON.stringify(config));
    };

    ws.onmessage = async (event) => {
        // Handle both text (JSON control) and binary (video) frames
        if (event.data instanceof ArrayBuffer) {
            // Binary frame - video data
            const videoChunk = new Uint8Array(event.data);
            segmentQueue.push(videoChunk);
            pumpSegmentQueue();
        } else {
            // Text frame - JSON control message
            const msg = JSON.parse(event.data);

            if (msg.type === 'session_ready') {
                console.log("Session ready:", msg.data.session_id);
                stopBtn.disabled = false;

                // Start video playback with cross-browser compatibility
                // Mute initially to ensure autoplay works, then unmute
                // (video from avatar typically has no audio track, but this ensures compatibility)
                avatarVideo.muted = true;
                const playPromise = avatarVideo.play();
                if (playPromise !== undefined) {
                    playPromise
                        .then(() => {
                            console.log('Video playback started successfully');
                            // Unmute after successful play (for browsers that require muted autoplay)
                            avatarVideo.muted = false;
                        })
                        .catch(err => {
                            console.error('Video play() failed:', err);
                            // Try again with user gesture requirement notification
                        });
                }

                // Start microphone
                await startAudioCapture();
                setStatus('listening');

                // Start buffer monitoring and playback watchdog
                startBufferMonitoring();
                startPlaybackWatchdog();

            } else if (msg.type === 'status') {
                setStatus(msg.data);
            }
        }
    };

    ws.onclose = () => {
        console.log("WebSocket closed");
        stopSession();
    };

    ws.onerror = (error) => {
        console.error("WebSocket error:", error);
    };
};

stopBtn.onclick = stopSession;
if (floatingStopBtn) {
    floatingStopBtn.onclick = stopSession;
}

function stopSession() {
    // Mark session as inactive FIRST to stop watchdog/event handlers
    isSessionActive = false;

    // Exit mobile full-screen mode
    document.body.classList.remove('session-active');
    document.body.classList.remove('sidebar-collapsed');

    startBtn.disabled = false;
    stopBtn.disabled = true;

    if (ws) {
        ws.close();
        ws = null;
    }
    stopAudioCapture();
    stopBufferMonitoring();
    stopPlaybackWatchdog();

    statusBadge.style.display = 'none';
    micIndicator.style.display = 'none';

    // Clear any pending status changes
    pendingStatusTimeouts.forEach(t => clearTimeout(t));
    pendingStatusTimeouts = [];

    // Clear video segment queue
    segmentQueue = [];

    // Clean up MediaSource properly
    if (mediaSource && mediaSource.readyState === 'open') {
        try {
            mediaSource.endOfStream();
        } catch (e) {
            console.warn('Error ending media stream:', e);
        }
    }
    mediaSource = null;
    sourceBuffer = null;

    // Reset video element to clear any residual frames
    // This fixes the "residual 1-2 seconds of video" issue
    avatarVideo.pause();
    avatarVideo.removeAttribute('src');
    avatarVideo.load();  // Reset the video element completely
}
