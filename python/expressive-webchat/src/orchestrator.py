import asyncio
import json
import logging
import re
from typing import AsyncIterator, Awaitable, Callable, Optional

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from deepgram.extensions.types.sockets.listen_v1_control_message import ListenV1ControlMessage
from litellm import acompletion

from .avatartalk_client import AvatarTalkClient
from .config import (
    ASRModel,
    Expression,
    get_asr_model_for_language,
    get_deepgram_language_code,
    get_error_message,
    get_language_display_name,
    get_timeout_message,
    settings,
)

logger = logging.getLogger(__name__)


class ConversationOrchestrator:
    def __init__(self):
        """Initialize the orchestrator."""
        self.avatartalk = AvatarTalkClient(
            url=settings.AVATARTALK_API_BASE,
            api_key=settings.AVATARTALK_API_KEY,
            connect_timeout=settings.WS_CONNECT_TIMEOUT,
        )
        logger.info(f"Orchestrator initialized: url={settings.AVATARTALK_API_BASE}")

        # Deepgram setup (SDK 5.3.0)
        self.deepgram = AsyncDeepgramClient(api_key=settings.DEEPGRAM_API_KEY)
        self.dg_connection = None
        self.transcript_buffer = []  # Buffer for turn detection
        self.dg_listen_task = None
        self._dg_connect_lock = asyncio.Lock()

        # Internal Deepgram streaming state
        self._dg_audio_queue: Optional[asyncio.Queue] = None
        self._dg_worker_task: Optional[asyncio.Task] = None
        self._pending_tasks: set[asyncio.Task] = set()  # Track background tasks

        # Language and ASR model configuration
        self.language: str = "en"
        self.asr_model: ASRModel = ASRModel.FLUX
        self.deepgram_language: str = "en"

        # State
        self.is_listening = False
        self.is_avatar_speaking = False
        self.session_active = False
        self.avatar_turn_active = False  # True from EOT until dynamic speech completes
        self._ignore_transcripts = False  # Ignore transcripts during avatar's turn
        self._pause_audio_sending = False  # Gate to stop sending audio to Deepgram
        self.audio_sample_rate = 16000
        self.audio_channels = 1
        self.audio_configured = False
        self.use_pregen: bool = True  # Whether to use pregenerated videos

        # Expressive mode: LLM controls expression dynamically
        self.expressive_mode: bool = False
        self.current_expression: str = Expression.default().value  # Current/default expression

        self.conversation_history: list[dict] = []
        self.max_history_messages = 30

        # Callbacks
        self.on_status_change: Optional[Callable[[str], Awaitable[None]]] = None
        # Called when AvatarTalk streaming session is ready. Signature: (session_id)
        self.on_session_ready: Optional[Callable[[str], Awaitable[None]]] = None
        # Called when video data is received. Signature: (video_bytes)
        # This allows forwarding video chunks to the browser via the client WebSocket
        self.on_video_data: Optional[Callable[[bytes], Awaitable[None]]] = None

    async def start_session(
        self,
        avatar: str,
        expression: str,
        prompt: str,
        language: str = "en",
        use_pregen: bool = True,
    ):
        """Start the conversation session.

        Args:
            avatar: Avatar name (required)
            expression: Initial expression (required), use "expressive" for LLM-controlled expressions
            prompt: System prompt for LLM
            language: Language code, defaults to "en"
            use_pregen: Whether to use pregenerated videos for transitions
        """
        # Validate and sanitize prompt length
        if len(prompt) > settings.MAX_PROMPT_LENGTH:
            logger.warning(f"System prompt truncated from {len(prompt)} to {settings.MAX_PROMPT_LENGTH} chars")
            prompt = prompt[: settings.MAX_PROMPT_LENGTH]
        self.system_prompt = prompt
        self.use_pregen = use_pregen

        # Configure language and ASR model
        self.language = language
        self.asr_model = get_asr_model_for_language(language)
        self.deepgram_language = get_deepgram_language_code(language)
        logger.info(
            f"Language configured: {language} -> ASR model: {self.asr_model.value}, Deepgram lang: {self.deepgram_language}"
        )

        # Handle expressive mode: LLM dynamically controls expression
        if expression == "expressive":
            self.expressive_mode = True
            self.current_expression = Expression.default().value  # Start with neutral for silence videos
            effective_expression = Expression.default().value
            logger.info(f"Starting session in EXPRESSIVE mode: avatar={avatar}, initial_expression=neutral")
        else:
            self.expressive_mode = False
            self.current_expression = expression
            effective_expression = expression
            logger.info(f"Starting session: avatar={avatar}, expression={expression}, use_pregen={use_pregen}")

        # Connect to AvatarTalk API
        await self.avatartalk.connect(
            avatar=avatar,
            expression=effective_expression,
            language=language,
        )
        self.avatartalk.on_state_change = self._handle_avatartalk_state_change
        self.avatartalk.on_ready_to_listen = self._handle_ready_to_listen
        self.avatartalk.on_session_ready = self._handle_avatartalk_session_ready
        self.avatartalk.on_video_data = self._handle_video_data

        # Start AvatarTalk session
        await self.avatartalk.start_session(
            avatar=avatar,
            expression=effective_expression,
            language=language,
            expressive_mode=self.expressive_mode,
        )

        self.session_active = True

    async def stop_session(self):
        """Stop the conversation session and cleanup resources."""
        self.session_active = False
        self.is_listening = False

        # Stop Deepgram connection
        # Signal the worker (if any) that no more audio will be sent.
        if self._dg_audio_queue is not None:
            try:
                await self._dg_audio_queue.put(None)
            except Exception as e:
                logger.error(f"Error signaling Deepgram worker to stop: {e}")

        # Cancel worker and listener tasks if they are still running.
        if self._dg_worker_task:
            self._dg_worker_task.cancel()
            try:
                await self._dg_worker_task
            except asyncio.CancelledError:
                pass
            self._dg_worker_task = None

        if self.dg_listen_task:
            self.dg_listen_task.cancel()
            try:
                await self.dg_listen_task
            except asyncio.CancelledError:
                pass
            self.dg_listen_task = None

        self.dg_connection = None
        self._dg_audio_queue = None

        # Cancel any pending background tasks
        for task in list(self._pending_tasks):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._pending_tasks.clear()

        # Disconnect from AvatarTalk
        await self.avatartalk.disconnect()

    async def process_audio(self, audio_data: bytes):
        """Process incoming audio from user and send to Deepgram."""
        if not self.session_active or not self.is_listening:
            return

        # Ensure we've received audio configuration from the browser before
        # attempting to connect to Deepgram. This guarantees that
        # self.audio_sample_rate matches the actual stream.
        if not self.audio_configured:
            logger.warning("Dropping audio frame because audio_config has not been received yet")
            return

        # Lazily establish Deepgram connection + worker on first audio frame,
        # using the configured sample rate.
        try:
            await self._ensure_deepgram_connection()
        except Exception as e:
            logger.error(f"Unable to establish Deepgram connection while processing audio: {e}")
            return

        if not self._dg_audio_queue:
            logger.error("Deepgram audio queue is not available; dropping audio chunk")
            return

        try:
            logger.debug(f"Queueing audio chunk for Deepgram: {len(audio_data)} bytes at {self.audio_sample_rate} Hz")
            await self._dg_audio_queue.put(audio_data)
        except Exception as e:
            logger.error(f"Error queueing audio for Deepgram: {e}")

    async def send_buffer_status(self, buffered_ms: float, playback_position: Optional[float] = None):
        """Forward browser video buffer status to AvatarTalk for adaptive streaming."""
        if not self.avatartalk or not self.avatartalk.ws:
            return

        try:
            await self.avatartalk.send_buffer_status(buffered_ms, playback_position or 0.0)
        except Exception as e:
            logger.error(f"Error forwarding buffer_status to AvatarTalk: {e}")

    def set_audio_config(self, sample_rate: int | None = None, channel_count: int | None = None):
        if sample_rate:
            self.audio_sample_rate = int(sample_rate)
        if channel_count:
            self.audio_channels = int(channel_count)

        self.audio_configured = True
        logger.info(f"Applied audio_config: sample_rate={self.audio_sample_rate}, channels={self.audio_channels}")

    async def _connect_deepgram_flux(self):
        """
        Deepgram Flux worker: opens a Flux listen.v2 connection and streams audio
        from the internal queue while handling incoming events.

        Flux is used for English only and provides built-in turn detection via
        EndOfTurn events.
        """
        try:
            logger.info(f"Connecting to Deepgram Flux (listen.v2) with sample_rate={self.audio_sample_rate}")

            # Connect to Flux via Listen v2 WebSocket API.
            # Note: listen.v2 accepts model, encoding, sample_rate and various
            # turn-taking parameters (eot_threshold, eot_timeout_ms, etc.). We
            # rely on Flux's defaults for turn detection.
            async with self.deepgram.listen.v2.connect(
                model="flux-general-en",
                encoding="linear16",
                sample_rate=str(self.audio_sample_rate),
            ) as connection:
                self.dg_connection = connection

                # Define message handler for Flux listen.v2 streaming.
                def on_message(message) -> None:
                    msg_type = getattr(message, "type", None)

                    # Connected event (initial handshake/configuration)
                    if msg_type == "Connected":
                        logger.info("Deepgram Flux connected event received")
                        return

                    # Fatal error event
                    if msg_type == "FatalError":
                        error_message = getattr(message, "message", None)
                        logger.error(f"Deepgram Flux fatal error: {error_message or message}")
                        # Stop listening on fatal error; the worker loop will exit
                        self.is_listening = False
                        return

                    # TurnInfo events carry transcript updates and EndOfTurn signals
                    if msg_type == "TurnInfo":
                        # Ignore transcripts during avatar's turn
                        if self._ignore_transcripts:
                            logger.debug(f"Ignoring Flux TurnInfo during avatar turn")
                            return

                        event = getattr(message, "event", None)
                        transcript_text = getattr(message, "transcript", "") or ""

                        if transcript_text:
                            logger.debug(f"Flux TurnInfo ({event}): {transcript_text}")
                            # Accumulate transcript text for this turn
                            self.transcript_buffer.append(transcript_text)

                        if event == "EndOfTurn":
                            # Prefer the transcript from this event; otherwise fall
                            # back to any accumulated buffer.
                            final_transcript = transcript_text or " ".join(self.transcript_buffer)
                            final_transcript = final_transcript.strip()
                            if final_transcript:
                                logger.info(f"Flux EndOfTurn detected: '{final_transcript}'")
                                # SET FLAGS SYNCHRONOUSLY before scheduling async task
                                # This prevents race condition where more audio/transcripts
                                # arrive before the async task runs
                                self._ignore_transcripts = True
                                self._pause_audio_sending = True
                                self.transcript_buffer.clear()
                                logger.info("Turn switch: flags set synchronously, scheduling handler")
                                self._create_tracked_task(self._handle_user_turn(final_transcript))

                        return

                def on_open(_):
                    logger.info(" Deepgram Flux connection opened (listen.v2)")

                def on_close(event):
                    logger.info(f"Deepgram Flux connection closed: {event}")
                    # Mark connection as closed so we don't continue sending audio
                    self.dg_connection = None
                    self.is_listening = False
                    # Keep session_active; stop_session() will flip it and clean up

                def on_error(error):
                    logger.error(f"Deepgram Flux error: {error}")

                # Register event handlers
                connection.on(EventType.OPEN, on_open)
                connection.on(EventType.MESSAGE, on_message)
                connection.on(EventType.CLOSE, on_close)
                connection.on(EventType.ERROR, on_error)

                # Start listening in background
                self.dg_listen_task = asyncio.create_task(connection.start_listening())

                logger.info(" Deepgram Flux connected and listening (listen.v2)")

                # Main send loop: read from the internal queue and forward to Deepgram
                while self.session_active and self._dg_audio_queue is not None:
                    chunk = await self._dg_audio_queue.get()
                    if chunk is None:
                        break
                    # Check audio gate - skip sending if paused (turn switched)
                    if self._pause_audio_sending:
                        logger.debug("Skipping audio chunk - audio sending paused")
                        continue
                    try:
                        # For listen.v2, the enhanced send_media method accepts
                        # raw bytes; constructing a ListenV2MediaMessage directly
                        # would require keyword args and results in BaseModel
                        # __init__ errors if used positionally.
                        await connection.send_media(chunk)
                    except Exception as e:
                        logger.error(f"Error sending audio to Deepgram: {e}")
                        break

                # Allow any remaining events to be processed before closing
                await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"Failed to connect to Deepgram Flux: {e}")
        finally:
            # Ensure listener task is cleaned up
            if self.dg_listen_task:
                if not self.dg_listen_task.done():
                    self.dg_listen_task.cancel()
                    try:
                        await self.dg_listen_task
                    except asyncio.CancelledError:
                        pass
                self.dg_listen_task = None

            self.dg_connection = None

    async def _connect_deepgram_nova(self):
        """
        Deepgram Nova worker: opens a Nova-3 or Nova-2 connection for non-English languages.

        Uses listen.v1 with utterance_end_ms for turn detection instead of
        Flux's built-in EndOfTurn events.
        """
        # Determine model based on ASR model type
        if self.asr_model == ASRModel.NOVA3:
            model = "nova-3"
        else:
            model = "nova-2"

        logger.info(
            f"Connecting to Deepgram {model} (listen.v1) with "
            f"sample_rate={self.audio_sample_rate}, language={self.deepgram_language}"
        )

        try:
            # Connect to Nova via Listen v1 WebSocket API with turn detection params
            async with self.deepgram.listen.v1.connect(
                model=model,
                language=self.deepgram_language,
                encoding="linear16",
                sample_rate=str(self.audio_sample_rate),
                channels=str(self.audio_channels),
                punctuate="true",
                interim_results="true",
                utterance_end_ms="1000",  # Detect end of utterance after 1s silence
                vad_events="true",
                endpointing="500",  # 500ms silence for endpointing
            ) as connection:
                self.dg_connection = connection

                # Define message handler for Nova listen.v1 streaming
                def on_message(message) -> None:
                    msg_type = getattr(message, "type", None)

                    # Handle Results messages (transcripts)
                    if msg_type == "Results":
                        # Check if this is a from_finalize response (ignore it)
                        from_finalize = getattr(message, "from_finalize", False)
                        if from_finalize:
                            logger.debug("Ignoring from_finalize response")
                            return

                        # Ignore transcripts during avatar's turn
                        if self._ignore_transcripts:
                            logger.debug("Ignoring Nova transcript during avatar turn")
                            return

                        try:
                            channel = getattr(message, "channel", None)
                            if not channel:
                                return
                            alternatives = getattr(channel, "alternatives", [])
                            if not alternatives:
                                return

                            transcript = alternatives[0].transcript if alternatives else ""
                            is_final = getattr(message, "is_final", False)
                            speech_final = getattr(message, "speech_final", False)

                            if transcript:
                                logger.debug(
                                    f"Nova transcript (final={is_final}, speech_final={speech_final}): {transcript}"
                                )

                                if speech_final:
                                    # speech_final indicates end of an utterance
                                    self.transcript_buffer.append(transcript)
                                    final_transcript = " ".join(self.transcript_buffer).strip()
                                    if final_transcript:
                                        logger.info(f"Nova speech_final detected: '{final_transcript}'")
                                        # SET FLAGS SYNCHRONOUSLY before scheduling async task
                                        self._ignore_transcripts = True
                                        self._pause_audio_sending = True
                                        self.transcript_buffer.clear()
                                        logger.info("Turn switch: flags set synchronously, scheduling handler")
                                        self._create_tracked_task(self._handle_user_turn(final_transcript))
                                elif is_final:
                                    # Accumulate final transcripts for the current utterance
                                    self.transcript_buffer.append(transcript)
                        except Exception as e:
                            logger.error(f"Error processing Nova transcript: {e}")
                        return

                    # Handle UtteranceEnd messages (backup turn detection)
                    if msg_type == "UtteranceEnd":
                        # Ignore during avatar's turn
                        if self._ignore_transcripts:
                            logger.debug("Ignoring Nova UtteranceEnd during avatar turn")
                            return

                        if self.transcript_buffer:
                            final_transcript = " ".join(self.transcript_buffer).strip()
                            if final_transcript:
                                logger.info(f"Nova UtteranceEnd detected: '{final_transcript}'")
                                # SET FLAGS SYNCHRONOUSLY before scheduling async task
                                self._ignore_transcripts = True
                                self._pause_audio_sending = True
                                self.transcript_buffer.clear()
                                logger.info("Turn switch: flags set synchronously, scheduling handler")
                                self._create_tracked_task(self._handle_user_turn(final_transcript))
                        return

                    # Handle SpeechStarted
                    if msg_type == "SpeechStarted":
                        logger.debug("Nova speech started")
                        return

                    # Handle Metadata
                    if msg_type == "Metadata":
                        logger.debug(f"Nova metadata: {message}")
                        return

                def on_open(_):
                    logger.info("Deepgram Nova connection opened (listen.v1)")

                def on_close(event):
                    logger.info(f"Deepgram Nova connection closed: {event}")
                    self.dg_connection = None
                    self.is_listening = False

                def on_error(error):
                    logger.error(f"Deepgram Nova error: {error}")

                # Register event handlers
                connection.on(EventType.OPEN, on_open)
                connection.on(EventType.MESSAGE, on_message)
                connection.on(EventType.CLOSE, on_close)
                connection.on(EventType.ERROR, on_error)

                # Start listening in background
                self.dg_listen_task = asyncio.create_task(connection.start_listening())

                # KeepAlive task to prevent NET-0001 timeout (10s without audio)
                keepalive_task = asyncio.create_task(self._nova_keepalive_loop(connection))

                logger.info(f"Deepgram {model} connected and listening (listen.v1)")

                # Main send loop: read from the internal queue and forward to Deepgram
                while self.session_active and self._dg_audio_queue is not None:
                    chunk = await self._dg_audio_queue.get()
                    if chunk is None:
                        break
                    # Check audio gate - skip sending if paused (turn switched)
                    if self._pause_audio_sending:
                        logger.debug("Skipping audio chunk - audio sending paused")
                        continue
                    try:
                        await connection.send_media(chunk)
                    except Exception as e:
                        logger.error(f"Error sending audio to Deepgram Nova: {e}")
                        break

                # Cancel keepalive task
                keepalive_task.cancel()
                try:
                    await keepalive_task
                except asyncio.CancelledError:
                    pass

                # Allow any remaining events to be processed before closing
                await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"Failed to connect to Deepgram Nova: {e}")
        finally:
            # Ensure listener task is cleaned up
            if self.dg_listen_task:
                if not self.dg_listen_task.done():
                    self.dg_listen_task.cancel()
                    try:
                        await self.dg_listen_task
                    except asyncio.CancelledError:
                        pass
                self.dg_listen_task = None

            self.dg_connection = None

    async def _nova_keepalive_loop(self, connection):
        """Send KeepAlive messages every 5 seconds to prevent NET-0001 timeout."""
        keepalive_msg = ListenV1ControlMessage(type="KeepAlive")
        while True:
            await asyncio.sleep(5)
            try:
                await connection.send_control(keepalive_msg)
                logger.debug("Nova KeepAlive sent")
            except Exception as e:
                logger.warning(f"Failed to send Nova KeepAlive: {e}")
                break

    async def _ensure_deepgram_connection(self):
        """Create a Deepgram connection if one isn't active."""
        if self._dg_worker_task and not self._dg_worker_task.done():
            return
        async with self._dg_connect_lock:
            if self._dg_worker_task and not self._dg_worker_task.done():
                return
            if self._dg_audio_queue is None:
                self._dg_audio_queue = asyncio.Queue()

            # Route to appropriate connection method based on ASR model
            if self.asr_model == ASRModel.FLUX:
                self._dg_worker_task = asyncio.create_task(self._connect_deepgram_flux())
            else:
                # Nova-3 or Nova-2
                self._dg_worker_task = asyncio.create_task(self._connect_deepgram_nova())

    async def _drain_audio_queue(self):
        """Drain pending audio from the queue to prevent stale audio from being sent.

        Called when turn switches to avatar to discard any queued audio chunks
        that would otherwise be sent to Deepgram and potentially trigger unwanted
        transcripts from continued user speech after EOT detection.
        """
        if self._dg_audio_queue is None:
            return

        drained_count = 0
        while not self._dg_audio_queue.empty():
            try:
                self._dg_audio_queue.get_nowait()
                drained_count += 1
            except asyncio.QueueEmpty:
                break

        if drained_count > 0:
            logger.info(f"Drained {drained_count} audio chunks from queue on turn switch")

    async def _send_deepgram_finalize(self):
        """Send Finalize message to Deepgram to flush any buffered audio.

        This tells Deepgram to process all remaining audio and return final results,
        preventing leftover transcripts from arriving after turn switch.
        See: https://developers.deepgram.com/docs/finalize

        Note: Finalize is only supported for Nova (listen.v1), not Flux (listen.v2).
        """
        # Finalize only works with Nova (listen.v1), not Flux (listen.v2)
        if self.asr_model == ASRModel.FLUX:
            logger.debug("Finalize not supported for Flux, skipping")
            return

        if self.dg_connection is None:
            logger.debug("No Deepgram connection, skipping Finalize")
            return

        try:
            # Send Finalize control message (Nova only)
            finalize_msg = ListenV1ControlMessage(type="Finalize")
            await self.dg_connection.send_control(finalize_msg)
            logger.info("Sent Finalize message to Deepgram Nova")
        except Exception as e:
            logger.warning(f"Failed to send Finalize to Deepgram: {e}")

    def _create_tracked_task(self, coro) -> asyncio.Task:
        """Create a task and track it to handle exceptions."""
        task = asyncio.create_task(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task) -> None:
        """Handle completed background tasks and log any exceptions."""
        self._pending_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"Background task failed: {exc}", exc_info=exc)

    async def _handle_avatartalk_session_ready(self, session_id: str):
        """Propagate AvatarTalk session_ready events to any registered listener."""
        logger.info(f"AvatarTalk Session Ready (orchestrator): {session_id}")
        if self.on_session_ready:
            await self.on_session_ready(session_id)

    async def _handle_video_data(self, video_bytes: bytes):
        """Forward video data from AvatarTalk to the registered callback.

        This enables the client backend to proxy video chunks directly to the browser
        via the unified WebSocket connection.
        """
        if self.on_video_data:
            await self.on_video_data(video_bytes)

    async def _handle_user_turn(self, text: str):
        """Handle detected user speech with streaming LLM response."""
        # Note: _ignore_transcripts and _pause_audio_sending are already set
        # synchronously in the on_message callback before this task was scheduled
        self.is_listening = False
        self.avatar_turn_active = True  # Mark turn as active until ready_to_listen

        # Drain any remaining audio from queue
        await self._drain_audio_queue()

        # Send Finalize to Deepgram to flush any buffered audio on server side
        # This ensures no leftover transcripts arrive after turn switch
        await self._send_deepgram_finalize()

        if self.on_status_change:
            await self.on_status_change("thinking")

        # First trigger: Flux EndOfTurn → start an EoT pregenerated segment.
        # This makes the avatar react immediately while the LLM response is
        # being generated. Only triggered when use_pregen is enabled.
        if self.use_pregen:
            try:
                await self.avatartalk.send_turn_start(expression=self.current_expression)
            except Exception as e:
                logger.error(f"Error sending turn_start to AvatarTalk: {e}")

        # Stream LLM response and send sentences incrementally to AvatarTalk
        try:
            first_sentence = True
            expression_used = self.current_expression

            async for sentence, expression in self._stream_response(text):
                if not sentence.strip():
                    continue

                logger.debug(f"Received from _stream_response: sentence='{sentence[:50]}...', expression={expression}")

                # Use expression from first sentence for consistency
                if first_sentence:
                    if self.expressive_mode:
                        # In expressive mode, use LLM's expression or fallback to current
                        logger.info(f"Expressive mode: LLM expression={expression}, current={self.current_expression}")
                        expression_used = expression if expression else self.current_expression
                        # Update current expression for next interactions
                        if expression:
                            self.current_expression = expression
                            logger.info(f"Expressive mode: switching to '{expression}'")
                    else:
                        # Static mode: always use the configured expression
                        expression_used = self.current_expression

                    logger.info(f"Avatar starting reply: {sentence} ({expression_used})")
                    # First sentence: start dynamic-only flow
                    await self.avatartalk.send_text(
                        sentence,
                        expression=expression_used,
                        mode="dynamic_only",
                    )
                    first_sentence = False
                else:
                    # Subsequent sentences: append to ongoing speech
                    logger.info(f"Avatar appending: {sentence}")
                    await self.avatartalk.append_text(sentence)

            # Signal that LLM streaming is complete
            if not first_sentence:  # Only if we sent at least one sentence
                await self.avatartalk.finish_text_stream()
                logger.info("LLM streaming complete, signaled server")
                # Clear avatar_turn_active - we've sent all text to server.
                # Next ready_to_listen from server will enable mic.
                self.avatar_turn_active = False

            # Note: We don't set is_listening = True here.
            # We wait for AvatarTalk to tell us it finished (DYNAMIC -> SILENCE)
            # via the ready_to_listen signal.

        except Exception as e:
            logger.error(f"LLM streaming error: {e}")
            # If error, go back to listening
            self.is_listening = True
            self.avatar_turn_active = False
            if self.on_status_change:
                await self.on_status_change("listening")

    async def _stream_response(self, user_text: str) -> AsyncIterator[tuple[str, Optional[str]]]:
        """Stream LLM response and yield complete sentences with expression.

        Yields tuples of (sentence_text, expression) where expression is only
        provided with the first sentence (extracted from JSON prefix if available).
        """
        # Collect full response for history
        full_response_text = ""

        try:
            # Build messages with conversation history
            # Add language instruction if not English
            language_instruction = ""
            if self.language != "en":
                lang_name = get_language_display_name(self.language)
                language_instruction = (
                    f"\n\nIMPORTANT: You MUST respond in {lang_name}. All your responses should be in {lang_name}."
                )

            expressions_list = ", ".join(Expression.values())
            messages = [
                {
                    "role": "system",
                    "content": (
                        f"{self.system_prompt}{language_instruction}\n\n"
                        "IMPORTANT: Start your response with a JSON prefix containing the expression, "
                        "then a newline, then your natural response text.\n"
                        'Format: {"expression": "<emotion>"}\n<your response>\n\n'
                        f"Expressions: {expressions_list}\n"
                        f'Example:\n{{"expression": "{Expression.HAPPY.value}"}}\nHello! It\'s great to meet you.'
                    ),
                },
            ]
            # Add conversation history
            messages.extend(self.conversation_history)
            # Add current user message
            messages.append({"role": "user", "content": user_text})

            response = await asyncio.wait_for(
                acompletion(
                    model=settings.LLM_MODEL,
                    messages=messages,
                    api_key=settings.OPENAI_API_KEY,
                    stream=True,
                ),
                timeout=settings.LLM_TIMEOUT,
            )

            accumulator = SentenceAccumulator()
            extracted_expression = None
            expression_extracted = False
            total_content = ""

            async for chunk in response:
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)

                if content:
                    total_content += content
                    # Try to extract expression from JSON prefix
                    if not expression_extracted:
                        expr_result, remaining = accumulator.try_extract_expression(content)
                        if expr_result:
                            extracted_expression = expr_result
                            expression_extracted = True
                            content = remaining
                            logger.info(f"Extracted expression from LLM: '{extracted_expression}'")
                        elif accumulator.buffer_has_expression_prefix():
                            # Still accumulating JSON prefix, don't emit yet
                            continue

                    # Add content and yield complete sentences
                    for sentence in accumulator.add_chunk(content):
                        full_response_text += sentence + " "
                        # Yield expression only with first sentence
                        yield (sentence, extracted_expression)
                        logger.debug(f"Yielded sentence with expression={extracted_expression}: {sentence[:50]}...")
                        extracted_expression = None  # Only yield expression once

            # Yield any remaining content as final sentence
            logger.info(f"Total content: {total_content}")
            final = accumulator.flush()
            if final.strip():
                full_response_text += final + " "
                yield (final, None)

            # Update conversation history
            self._add_to_history("user", user_text)
            self._add_to_history("assistant", full_response_text.strip())

        except asyncio.TimeoutError:
            logger.error(f"LLM response timed out after {settings.LLM_TIMEOUT}s")
            yield (get_timeout_message(self.language), Expression.default().value)
        except Exception as e:
            logger.error(f"Error streaming response: {e}")
            yield (get_error_message(self.language), Expression.default().value)

    async def _generate_response(self, user_text: str) -> dict:
        """Generate response using LiteLLM (non-streaming fallback)."""
        try:
            expressions_list = ", ".join(Expression.values())
            messages = [
                {
                    "role": "system",
                    "content": f"{self.system_prompt}\n\nYou must respond in JSON format with two fields: 'text' (your reply) and 'expression' (one of: {expressions_list}).",
                },
                {"role": "user", "content": user_text},
            ]

            response = await asyncio.wait_for(
                acompletion(
                    model=settings.LLM_MODEL,
                    messages=messages,
                    api_key=settings.OPENAI_API_KEY,
                    response_format={"type": "json_object"},
                ),
                timeout=settings.LLM_TIMEOUT,
            )

            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return {"text": get_error_message(self.language), "expression": Expression.default().value}

    def _add_to_history(self, role: str, content: str) -> None:
        """Add a message to conversation history, trimming to max length."""
        if not content.strip():
            return

        self.conversation_history.append({"role": role, "content": content})

        # Trim to max messages (keep most recent)
        if len(self.conversation_history) > self.max_history_messages:
            self.conversation_history = self.conversation_history[-self.max_history_messages :]

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.conversation_history = []
        logger.info("Conversation history cleared")

    async def _handle_avatartalk_state_change(self, from_state: str, to_state: str):
        """Handle state changes from the AvatarTalk server and update UI accordingly.

        State mapping:
        - silence_to_pregen, pregen_video, pregen_to_dynamic → "thinking"
        - dynamic_speech, dynamic_to_silence → "speaking"
        - silence → wait for ready_to_listen signal
        """
        logger.info(f"AvatarTalk State: {from_state} -> {to_state}")

        # States that indicate "thinking" (before dynamic speech starts)
        thinking_states = {"silence_to_pregen", "pregen_video", "pregen_to_dynamic"}
        # States that indicate "speaking" (dynamic speech active)
        speaking_states = {"dynamic_speech", "dynamic_to_silence"}

        if to_state in thinking_states:
            self.is_listening = False
            if self.on_status_change:
                await self.on_status_change("thinking")
        elif to_state in speaking_states:
            self.is_listening = False
            if self.on_status_change:
                await self.on_status_change("speaking")
        # Note: silence state is handled by ready_to_listen signal

    async def _handle_ready_to_listen(self):
        """Called when server signals that buffer has drained and mic can open.

        This signal indicates the avatar's turn is complete and user can speak.
        We track avatar_turn_active to prevent premature mic activation when
        ready_to_listen arrives before LLM finishes generating text.
        """
        logger.info(f"Server ready_to_listen signal received (avatar_turn_active={self.avatar_turn_active})")
        if not self.session_active:
            return

        # IMPORTANT: If avatar_turn_active is True, it means we initiated a turn
        # (sent turn_start) but the LLM hasn't finished generating text yet.
        # In this case, ignore the ready_to_listen - server sent it because
        # pregen ended and it doesn't know text is coming. Keep mic OFF.
        if self.avatar_turn_active:
            logger.info("Ignoring ready_to_listen - avatar turn still active (waiting for LLM)")
            return

        # Clear any accumulated transcripts and re-enable transcript processing
        self.transcript_buffer.clear()
        self._ignore_transcripts = False
        self._pause_audio_sending = False
        logger.info("Transcript processing re-enabled, audio sending resumed, buffer cleared")

        if not self.is_listening:
            logger.info("Enabling microphone for user input")
            self.is_listening = True
            if self.on_status_change:
                await self.on_status_change("listening")


class SentenceAccumulator:
    """Accumulates streaming tokens and emits complete sentences.

    Handles JSON expression prefix extraction and sentence boundary detection.
    """

    # Sentence-ending punctuation followed by space or end of string
    SENTENCE_END_PATTERN = re.compile(r"([.!?])(?:\s+|$)")
    # JSON expression prefix pattern
    EXPRESSION_PATTERN = re.compile(r'^\s*\{\s*"expression"\s*:\s*"(\w+)"\s*\}\s*\n?')

    def __init__(self):
        self.buffer = ""
        self._json_prefix_buffer = ""
        self._json_complete = False

    def try_extract_expression(self, content: str) -> tuple[Optional[str], str]:
        """Try to extract expression from JSON prefix.

        Returns (expression, remaining_content) if found, (None, content) otherwise.
        """
        if self._json_complete:
            return None, content

        self._json_prefix_buffer += content

        # Check if we have a complete JSON prefix
        match = self.EXPRESSION_PATTERN.match(self._json_prefix_buffer)
        if match:
            expression = match.group(1)
            remaining = self._json_prefix_buffer[match.end() :]
            self._json_complete = True
            self._json_prefix_buffer = ""
            return expression, remaining

        # If buffer is getting long without finding JSON, treat as regular text
        if len(self._json_prefix_buffer) > 100 or "\n" in self._json_prefix_buffer:
            # No JSON prefix found, return accumulated buffer as content
            remaining = self._json_prefix_buffer
            self._json_prefix_buffer = ""
            self._json_complete = True
            return None, remaining

        return None, ""

    def buffer_has_expression_prefix(self) -> bool:
        """Check if we're still accumulating a potential JSON prefix."""
        return bool(self._json_prefix_buffer) and not self._json_complete

    def add_chunk(self, content: str) -> list[str]:
        """Add a chunk of text and return any complete sentences."""
        if not content:
            return []

        self.buffer += content
        sentences = []

        # Find sentence boundaries
        while True:
            match = self.SENTENCE_END_PATTERN.search(self.buffer)
            if not match:
                if len(self.buffer) > 400:
                    sentences.append(self.buffer)
                    self.buffer = ""
                break

            # Extract complete sentence including punctuation
            end_pos = match.end()
            sentence = self.buffer[:end_pos].strip()
            self.buffer = self.buffer[end_pos:]

            if sentence:
                sentences.append(sentence)

        return sentences

    def flush(self) -> str:
        """Return any remaining content in the buffer."""
        remaining = self._json_prefix_buffer.strip() + self.buffer.strip()
        self._json_prefix_buffer = ""
        self.buffer = ""
        return remaining
