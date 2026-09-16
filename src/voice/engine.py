"""Core voice activation engine coordinating openWakeWord and Whisper STT."""
import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from src.voice.audio_io import (
    bring_app_window_to_foreground,
    is_speaking,
    play_cancel_chime,
    play_ready_chime,
    play_wake_chime,
    stop_speaking,
)
from src.voice.overlay import get_overlay

logger = logging.getLogger("aether.voice.engine")

SAMPLE_RATE = 16000
CHUNK_SIZE = 1280  # 80ms at 16kHz, required by openWakeWord


class VoiceEngine:
    """Continuous low-power keyword spotting and on-demand local transcription engine."""

    def __init__(
        self,
        wake_word: str = "aether",
        threshold: float = 0.5,
        stt_model_name: str = "base.en",
        input_device_index: int | None = None,
        silence_timeout_seconds: float = 1.0,
        max_recording_seconds: float = 12.0,
        on_speech_recognized: Callable[[str], None] | None = None,
        on_state_change: Callable[[str], None] | None = None,
        on_interrupt: Callable[[], None] | None = None,
        pop_window_on_wake: bool = False,
    ) -> None:
        self.wake_word = wake_word.strip().lower()
        self.threshold = threshold
        self.stt_model_name = stt_model_name
        self.input_device_index = input_device_index
        self.silence_timeout_seconds = silence_timeout_seconds
        self.max_recording_seconds = max_recording_seconds
        self.on_speech_recognized = on_speech_recognized
        self.on_state_change = on_state_change
        self.on_interrupt = on_interrupt
        self.pop_window_on_wake = pop_window_on_wake

        self.ambient_rms: float = 50.0
        self._state = "IDLE"
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._interrupt_event = threading.Event()
        self._is_handling_wake = threading.Lock()
        self._cooldown_until: float = 0.0
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
        self._whisper_model: Any = None
        self._oww_model: Any = None
        self._worker_thread: threading.Thread | None = None
        self._stream: Any = None

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, new_state: str) -> None:
        if self._state != new_state:
            self._state = new_state
            logger.info("VoiceEngine state -> %s", new_state)
            if self.on_state_change:
                try:
                    self.on_state_change(new_state)
                except Exception as e:
                    logger.debug("Error in state callback: %s", e)

    def _get_oww_key(self) -> str:
        """Map user-friendly wake word strings to openWakeWord model keys."""
        cleaned = self.wake_word.replace(" ", "_")
        key_map = {
            "aether": "aether",
            "hey_aether": "aether",
            "hey_jarvis": "hey_jarvis",
            "jarvis": "hey_jarvis",
            "alexa": "alexa",
            "hey_mycroft": "hey_mycroft",
            "mycroft": "hey_mycroft",
            "hey_rhasspy": "hey_rhasspy",
            "rhasspy": "hey_rhasspy",
            "timer": "timer",
            "weather": "weather",
        }
        return key_map.get(cleaned, cleaned)

    def _init_models(self) -> None:
        """Initialize openWakeWord model (for pre-trained models) and pre-load Whisper STT on CPU."""
        target_key = self._get_oww_key()
        pretrained_oww = {"hey_jarvis", "alexa", "hey_mycroft", "hey_rhasspy", "timer", "weather"}

        if target_key in pretrained_oww:
            import openwakeword
            from openwakeword.model import Model

            logger.info("Initializing openWakeWord model for '%s'...", target_key)
            self._oww_model = Model(wakeword_models=[target_key], inference_framework="onnx")
            self._oww_model.reset()
            logger.info("Loaded wake word model successfully.")
        else:
            logger.info("Custom wake word '%s' active — using Whisper keyword spotter.", self.wake_word)
            self._oww_model = None

        # Pre-load Whisper immediately on CPU (int8) so the first voice turn doesn't freeze or lag
        self._load_whisper_model()

    def _load_whisper_model(self) -> Any:
        """Initialize faster-whisper on CPU (int8) for rock-solid stability and zero VRAM footprint."""
        if self._whisper_model is not None:
            return self._whisper_model

        from faster_whisper import WhisperModel

        logger.info("Loading Whisper model '%s' on CPU (int8)...", self.stt_model_name)
        self._whisper_model = WhisperModel(
            self.stt_model_name,
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
        )
        logger.info("Whisper model '%s' loaded on CPU (int8) successfully.", self.stt_model_name)
        return self._whisper_model

    def start(self) -> None:
        """Start listening stream and audio processing thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            logger.warning("VoiceEngine is already running.")
            return

        self._stop_event.clear()
        self._pause_event.clear()

        self._worker_thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="Aether-VoiceEngine",
        )
        self._worker_thread.start()
        logger.info("VoiceEngine started successfully.")

    def stop(self) -> None:
        """Stop listening and terminate audio streams."""
        self._stop_event.set()
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        self._set_state("IDLE")
        logger.info("VoiceEngine stopped.")

    def pause(self) -> None:
        """Temporarily pause wake word listening."""
        self._pause_event.set()
        self._set_state("PAUSED")

    def resume(self) -> None:
        """Resume wake word listening."""
        self._pause_event.clear()
        self._set_state("LISTENING")

    def interrupt(self) -> None:
        """Interrupt active TTS speech, wake handling, or backend processing immediately."""
        logger.info("VoiceEngine interrupt requested.")
        self._interrupt_event.set()
        stop_speaking()
        self._drain_queue()
        self._set_state("LISTENING")
        if self.on_interrupt:
            try:
                self.on_interrupt()
            except Exception as e:
                logger.debug("Error in on_interrupt callback: %s", e)

    def trigger_listen_now(self) -> None:
        """Programmatically trigger direct speech recording without waiting for wake word."""
        if is_speaking() or self._state in ("PROCESSING", "SPEAKING"):
            self.interrupt()
        self._interrupt_event.clear()
        # If previous wake event is wrapping up, wait briefly for lock release
        for _ in range(5):
            if not self._is_handling_wake.locked():
                break
            time.sleep(0.05)
        if not self._is_handling_wake.locked():
            t = threading.Thread(
                target=self._handle_wake_event,
                daemon=True,
                name="Aether-DirectListen",
            )
            t.start()

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """Callback from sounddevice InputStream pushing raw PCM chunks into the queue."""
        if status:
            logger.debug("Audio status: %s", status)
        if not self._stop_event.is_set() and not self._pause_event.is_set():
            data = indata[:, 0].copy()
            try:
                self._audio_queue.put_nowait(data)
            except queue.Full:
                pass

    def _drain_queue(self) -> None:
        """Discard any accumulated frames in queue."""
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    def _run_loop(self) -> None:
        """Main processing thread managing state machine and audio streaming."""
        self._init_models()
        import sounddevice as sd

        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                blocksize=CHUNK_SIZE,
                device=self.input_device_index,
                channels=1,
                dtype="int16",
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as e:
            logger.error("Failed to open audio input stream: %s", e)
            self._set_state("ERROR")
            return

        self._set_state("LISTENING")
        target_key = self._get_oww_key()

        # Audio buffer for custom wake word spotting (when no openWakeWord model exists)
        speech_buffer: list[np.ndarray] = []
        speech_start_time: float | None = None
        consecutive_silent_chunks = 0
        was_speaking = False

        while not self._stop_event.is_set():
            now = time.time()
            from src.voice.audio_io import is_speaking
            currently_speaking = is_speaking() or self._state == "SPEAKING"

            # When speech output finishes, purge microphone echo buffer and cool down briefly
            if was_speaking and not currently_speaking:
                self._drain_queue()
                speech_buffer.clear()
                speech_start_time = None
                self._cooldown_until = time.time() + 0.35
            was_speaking = currently_speaking

            if self._pause_event.is_set() or (now < self._cooldown_until):
                self._drain_queue()
                speech_buffer.clear()
                speech_start_time = None
                time.sleep(0.05)
                continue

            try:
                frame = self._audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            frame_rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))

            # Update exponential moving average of ambient noise level ONLY when NOT speaking
            if not currently_speaking:
                self.ambient_rms = 0.96 * self.ambient_rms + 0.04 * frame_rms

            if self._oww_model is not None:
                # Tier 1: Wake word prediction via openWakeWord
                prediction = self._oww_model.predict(frame)
                score = 0.0
                for model_name, model_score in prediction.items():
                    if target_key in model_name:
                        score = float(model_score)
                        break

                if score >= self.threshold:
                    logger.info("Wake word '%s' detected (score: %.3f)", target_key, score)
                    is_active = currently_speaking or self._state in ("PROCESSING", "SPEAKING")
                    if is_active:
                        logger.info("Barge-in interrupt detected during active turn (state: %s, speaking: %s)", self._state, currently_speaking)
                        self.interrupt()
                    self._handle_wake_event()
            else:
                # Tier 1 Custom Spotter: Whisper keyword spotting for "aether"
                speech_thresh = max(15.0, self.ambient_rms * 1.3)
                if frame_rms >= speech_thresh:
                    if speech_start_time is None:
                        speech_start_time = now
                    speech_buffer.append(frame)
                    consecutive_silent_chunks = 0
                elif speech_start_time is not None:
                    speech_buffer.append(frame)
                    consecutive_silent_chunks += 1
                    buf_dur = len(speech_buffer) * CHUNK_SIZE / SAMPLE_RATE
                    # Evaluate when speaker pauses (~0.35s) or buffer reaches 1.8s
                    if consecutive_silent_chunks >= 4 or buf_dur >= 1.8:
                        if buf_dur >= 0.35:
                            audio_data = np.concatenate(speech_buffer).astype(np.float32) / 32768.0
                            whisper = self._load_whisper_model()
                            try:
                                segments, _ = whisper.transcribe(audio_data, language="en", beam_size=1)
                                text = " ".join(s.text for s in segments).strip().lower()
                                clean_text = re.sub(r"[^\w\s]", "", text)
                                wake_tokens = {
                                    "aether", "ether", "either", "eyther", "ayther", "eather",
                                    "author", "arthur", "heather", "ather", "athena", "edur", "edher",
                                } if "aether" in self.wake_word else {self.wake_word}
                                word_list = clean_text.split()

                                # Check for barge-in interrupt words while speaking (e.g. "stop", "quiet", "cancel", "pause")
                                interrupt_tokens = {"stop", "cancel", "quiet", "pause", "hush", "halt", "silence"}
                                if currently_speaking and any(w in interrupt_tokens for w in word_list):
                                    logger.info("Barge-in interrupt command detected during speech: '%s'", text)
                                    self.interrupt()
                                    speech_buffer.clear()
                                    speech_start_time = None
                                    consecutive_silent_chunks = 0
                                    continue

                                matched_token = None
                                wake_idx = -1
                                for i, w in enumerate(word_list):
                                    if w in wake_tokens or any(t in w for t in wake_tokens):
                                        matched_token = w
                                        wake_idx = i
                                        break

                                if matched_token is not None:
                                    logger.info("Custom wake word detected in speech: '%s' (matched '%s')", text, matched_token)
                                    if currently_speaking or self._state in ("PROCESSING", "SPEAKING"):
                                        self.interrupt()

                                    # Check if the user already spoke their command in this same utterance
                                    command_after_wake = " ".join(word_list[wake_idx + 1:]).strip() if wake_idx >= 0 else ""
                                    speech_buffer.clear()
                                    speech_start_time = None
                                    consecutive_silent_chunks = 0

                                    if len(command_after_wake.split()) >= 2:
                                        # User spoke a complete command together with the wake word (e.g. "aether what is the weather")
                                        logger.info("Direct voice command extracted from wake utterance: '%s'", command_after_wake)
                                        if self.pop_window_on_wake:
                                            bring_app_window_to_foreground()
                                        try:
                                            ov = get_overlay()
                                            ov.show("PROCESSING")
                                            ov.set_transcript(command_after_wake)
                                        except Exception:
                                            pass
                                        play_ready_chime()
                                        self._set_state("PROCESSING")
                                        cb = self.on_speech_recognized
                                        if cb:
                                            threading.Thread(
                                                target=cb,
                                                args=(command_after_wake,),
                                                daemon=True,
                                                name="Aether-DirectCommandWorker",
                                            ).start()
                                    else:
                                        # User only spoke the wake word (e.g. "aether" or "hey aether"), prompt for follow-up speech
                                        self._handle_wake_event()
                                    continue
                            except Exception as ex:
                                logger.debug("Error during custom wake word spotting: %s", ex)

                        speech_buffer.clear()
                        speech_start_time = None
                        consecutive_silent_chunks = 0

    def _handle_wake_event(self) -> None:
        """Transition to speech recording and transcribe once silence is detected."""
        if not self._is_handling_wake.acquire(blocking=False):
            return

        try:
            # 1. Bring desktop window to front only if explicitly configured
            if self.pop_window_on_wake:
                bring_app_window_to_foreground()

            # 2. Reset model feature buffer immediately so it does not re-trigger
            if self._oww_model:
                self._oww_model.reset()

            play_wake_chime()
            # Allow the ~250ms chime tone to clear speakers and mic input before recording
            time.sleep(0.28)
            self._drain_queue()
            try:
                get_overlay().show("RECORDING")
            except Exception:
                pass
            self._set_state("RECORDING")

            recorded_chunks: list[np.ndarray] = []
            silence_start: float | None = None
            speech_started = False
            consecutive_speech_chunks = 0
            start_time = time.time()

            # Dynamic adaptive thresholds based on ambient noise floor
            base_floor = max(15.0, self.ambient_rms)
            speech_threshold = max(base_floor * 1.30, base_floor + 32.0)
            silence_threshold = max(base_floor * 1.10, base_floor + 14.0)

            while not self._stop_event.is_set():
                if self._interrupt_event.is_set():
                    logger.info("Recording turn aborted by interrupt.")
                    return

                try:
                    frame = self._audio_queue.get(timeout=0.1)
                except queue.Empty:
                    frame = None

                if self._interrupt_event.is_set():
                    logger.info("Recording turn aborted by interrupt.")
                    return

                now = time.time()
                if frame is not None:
                    recorded_chunks.append(frame)

                    rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))

                    if rms >= speech_threshold:
                        consecutive_speech_chunks += 1
                        if consecutive_speech_chunks >= 2:
                            speech_started = True
                            silence_start = None
                    else:
                        consecutive_speech_chunks = 0
                        if rms <= silence_threshold:
                            if speech_started:
                                if silence_start is None:
                                    silence_start = now
                                elif now - silence_start >= max(1.8, self.silence_timeout_seconds):
                                    logger.info(
                                        "Silence detected after speech (total duration: %.2fs). Stopping recording.",
                                        now - start_time,
                                    )
                                    break
                    if not speech_started and (now - start_time >= 6.0):
                        if len(recorded_chunks) >= 16:
                            logger.info("Timeout reached with audio chunks captured. Attempting transcription.")
                            break
                        logger.info("No speech detected after trigger. Timing out.")
                        play_cancel_chime()
                        try:
                            get_overlay().show_timeout()
                        except Exception:
                            pass
                        return

                if now - start_time >= self.max_recording_seconds:
                    logger.info("Max recording duration reached (%.1fs).", self.max_recording_seconds)
                    break

            if self._interrupt_event.is_set():
                return

            if not recorded_chunks or (len(recorded_chunks) < 8 and not speech_started):
                play_cancel_chime()
                try:
                    get_overlay().show_timeout()
                except Exception:
                    pass
                return

            if self._interrupt_event.is_set():
                return

            play_ready_chime()
            self._set_state("TRANSCRIBING")

            # Concatenate audio chunks and normalize to float32
            full_audio_int16 = np.concatenate(recorded_chunks)
            full_audio_float32 = full_audio_int16.astype(np.float32) / 32768.0

            try:
                model = self._load_whisper_model()
                segments, info = model.transcribe(
                    full_audio_float32,
                    language="en",
                    beam_size=1,
                    vad_filter=False,
                )
                transcript = " ".join(seg.text.strip() for seg in segments).strip()
            except Exception as e:
                logger.error("Whisper transcription error: %s", e)
                transcript = ""

            if self._interrupt_event.is_set():
                logger.info("Transcription completed but turn was cancelled by interrupt. Discarding.")
                return

            if transcript:
                logger.info("Transcribed voice input: '%s'", transcript)
                try:
                    ov = get_overlay()
                    ov.set_state("PROCESSING")
                    ov.set_transcript(transcript)
                except Exception:
                    pass
                self._set_state("PROCESSING")
                cb = self.on_speech_recognized
                if cb:
                    threading.Thread(
                        target=cb,
                        args=(transcript,),
                        daemon=True,
                        name="Aether-VoiceTurnWorker",
                    ).start()
            else:
                logger.info("Transcription yielded empty text.")
                play_cancel_chime()
                try:
                    get_overlay().show_timeout()
                except Exception:
                    pass
                self._set_state("LISTENING")
        except Exception as e:
            logger.error("Error in wake event handler: %s", e)
            play_cancel_chime()
            try:
                get_overlay().show_timeout()
            except Exception:
                pass
            self._set_state("LISTENING")
        finally:
            if self._oww_model:
                self._oww_model.reset()
            self._drain_queue()
            self._cooldown_until = time.time() + 0.4
            if self._state not in ("PROCESSING", "SPEAKING"):
                self._set_state("LISTENING")
                try:
                    get_overlay().dismiss(delay_ms=4500)
                except Exception:
                    pass
            if self._is_handling_wake.locked():
                self._is_handling_wake.release()
