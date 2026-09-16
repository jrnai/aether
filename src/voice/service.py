"""Background service managing VoiceEngine and dispatching voice turns to Aether."""
import argparse
import logging
import queue
import threading
import time
from typing import Any

import httpx

from src.config import get_config
from src.voice.audio_io import speak_text
from src.voice.engine import VoiceEngine
from src.voice.overlay import get_overlay

logger = logging.getLogger("aether.voice.service")

_global_voice_service: Any = None
_service_lock = threading.Lock()


class VoiceService:
    """Orchestrates continuous voice activation and links it to Aether's chat/agent pipeline."""

    def __init__(
        self,
        wake_word: str | None = None,
        threshold: float | None = None,
        stt_model: str | None = None,
        tts_enabled: bool | None = None,
        api_base_url: str = "http://127.0.0.1:8000",
    ) -> None:
        cfg = get_config()
        self.wake_word = wake_word or getattr(cfg.voice, "wake_word", "aether")
        self.threshold = threshold if threshold is not None else getattr(cfg.voice, "threshold", 0.5)
        self.stt_model = stt_model or getattr(cfg.voice, "stt_model", "base.en")
        self.tts_enabled = tts_enabled if tts_enabled is not None else getattr(cfg.voice, "tts_enabled", True)
        self.tts_voice = getattr(cfg.voice, "tts_voice", "en-US-AriaNeural")
        self.api_base_url = api_base_url.rstrip("/")

        self._subscribers: list[Any] = []
        self._subscribers_lock = threading.Lock()
        self._last_transcript: str = ""
        self._last_answer: str = ""
        self._turn_id: int = 0
        self._cancel_turn_event = threading.Event()

        self.engine = VoiceEngine(
            wake_word=self.wake_word,
            threshold=self.threshold,
            stt_model_name=self.stt_model,
            silence_timeout_seconds=getattr(cfg.voice, "silence_timeout_seconds", 1.2),
            max_recording_seconds=getattr(cfg.voice, "max_recording_seconds", 15.0),
            on_speech_recognized=self._on_user_speech,
            on_state_change=self._on_engine_state_change,
            on_interrupt=self.interrupt,
            pop_window_on_wake=getattr(cfg.voice, "pop_window_on_wake", False),
        )
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def subscribe(self, q: Any) -> None:
        """Register a queue or listener for real-time voice event broadcasts."""
        with self._subscribers_lock:
            if q not in self._subscribers:
                self._subscribers.append(q)

    def unsubscribe(self, q: Any) -> None:
        """Unregister an event listener."""
        with self._subscribers_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast voice lifecycle events to all active listeners."""
        payload = {"type": event_type, "timestamp": time.time(), **data}
        with self._subscribers_lock:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(payload)
                except Exception:
                    pass

    def get_status(self) -> dict[str, Any]:
        """Return the current runtime status of the voice service."""
        return {
            "running": self._is_running,
            "state": self.engine.state,
            "wake_word": self.wake_word,
            "threshold": self.threshold,
            "stt_model": self.stt_model,
            "tts_enabled": self.tts_enabled,
            "pop_window_on_wake": getattr(self.engine, "pop_window_on_wake", False),
            "turn_id": self._turn_id,
            "last_transcript": self._last_transcript,
            "last_answer": self._last_answer,
        }

    def start(self) -> None:
        """Start the background voice listener."""
        if self._is_running:
            logger.info("VoiceService is already running.")
            return

        logger.info("Starting VoiceService (wake word: '%s')...", self.wake_word)
        self.engine.start()
        self._is_running = True

    def stop(self) -> None:
        """Stop the background voice listener."""
        if not self._is_running:
            return

        logger.info("Stopping VoiceService...")
        self.engine.stop()
        self._is_running = False

    def toggle(self) -> bool:
        """Toggle running state on or off. Returns new state."""
        if self._is_running:
            self.stop()
            return False
        else:
            self.start()
            return True

    def listen_now(self) -> bool:
        """Trigger immediate listening turn without waiting for wake word."""
        if not self._is_running:
            self.start()
            for _ in range(30):
                if self.engine._stream is not None:
                    break
                time.sleep(0.1)
        self.engine.trigger_listen_now()
        return True

    def _on_engine_state_change(self, new_state: str) -> None:
        logger.debug("Voice engine state changed to: %s", new_state)
        if new_state == "RECORDING":
            self._turn_id += 1
            self._cancel_turn_event.clear()
            self._last_transcript = ""
            self._last_answer = ""
        self.emit_event("state", {
            "state": new_state,
            "turn_id": self._turn_id,
            "transcript": self._last_transcript,
            "answer": self._last_answer,
        })

    def interrupt(self) -> None:
        """Interrupt active turn, stop TTS speech, and notify frontend."""
        if getattr(self, "_is_interrupting", False):
            return
        self._is_interrupting = True
        try:
            logger.info("VoiceService interrupt triggered for turn %s.", self._turn_id)
            self._cancel_turn_event.set()
            self._turn_id += 1
            self.emit_event("interrupt", {
                "turn_id": self._turn_id,
            })
            from src.voice.audio_io import stop_speaking
            stop_speaking()
            self.engine.interrupt()
            self.engine._drain_queue()
            self.engine._set_state("LISTENING")
        finally:
            self._is_interrupting = False

    def _on_user_speech(self, user_text: str) -> None:
        """Handle transcribed user command, emit events, and dispatch to Aether."""
        clean_prompt = user_text.strip()
        if not clean_prompt:
            return

        my_turn_id = self._turn_id
        try:
            if self._cancel_turn_event.is_set():
                logger.info("Turn %s was already cancelled prior to execution. Discarding.", my_turn_id)
                return
            self._last_transcript = clean_prompt
            self.emit_event("transcript", {
                "turn_id": my_turn_id,
                "text": clean_prompt,
            })
            self.emit_event("state", {
                "state": "PROCESSING",
                "turn_id": my_turn_id,
                "transcript": clean_prompt,
            })
            try:
                ov = get_overlay()
                ov.show("PROCESSING")
                ov.set_transcript(clean_prompt)
                ov.set_state("PROCESSING")
            except Exception:
                pass

            logger.info("Processing voice prompt for Aether (turn %s): '%s'", my_turn_id, clean_prompt)

            # 1. Direct in-process execution (fast, reliable, thread-safe, no self-network deadlocks)
            response_text = ""
            try:
                from src.storage.db import DatabaseManager
                from src.web.server import get_web_agent_loop

                agent = get_web_agent_loop()
                response_text = agent.run_turn(clean_prompt, cancel_event=self._cancel_turn_event)

                if my_turn_id != self._turn_id or self._cancel_turn_event.is_set():
                    logger.info("Turn %s was interrupted during agent inference. Discarding output.", my_turn_id)
                    return

                cfg = get_config()
                db = DatabaseManager(db_path=cfg.storage.database_path)
                sid = db.get_or_create_session("web_chat_default", title="Web Dashboard Chat")
                db.add_message(session_id=sid, role="user", content=clean_prompt)
                db.add_message(session_id=sid, role="assistant", content=response_text)
            except Exception as in_proc_err:
                if my_turn_id != self._turn_id or self._cancel_turn_event.is_set():
                    return
                logger.debug("In-process execution unavailable (%s), trying HTTP fallback...", in_proc_err)
                try:
                    with httpx.Client(timeout=60.0) as client:
                        res = client.post(
                            f"{self.api_base_url}/api/chat",
                            json={"message": clean_prompt},
                        )
                        if res.status_code == 200:
                            data = res.json()
                            response_text = data.get("response", "")
                except Exception as http_err:
                    logger.error("HTTP dispatch also failed: %s", http_err)
                    response_text = "I encountered an error processing your request."

            if my_turn_id != self._turn_id or self._cancel_turn_event.is_set():
                logger.info("Turn %s was interrupted before emission. Discarding output.", my_turn_id)
                return

            self._last_answer = response_text
            self.emit_event("answer", {
                "turn_id": my_turn_id,
                "transcript": clean_prompt,
                "text": response_text,
            })
            self.emit_event("state", {
                "state": "SPEAKING",
                "turn_id": my_turn_id,
                "transcript": clean_prompt,
                "answer": response_text,
            })

            # Show answer on floating overlay
            try:
                ov = get_overlay()
                ov.set_answer(response_text)
                ov.set_state("SPEAKING")
            except Exception:
                pass

            logger.info("Aether response (turn %s): %s", my_turn_id, response_text[:120] if response_text else "(empty)")

            # 3. Voice audio output if enabled
            if self.tts_enabled and response_text and not self._cancel_turn_event.is_set():
                self.engine._set_state("SPEAKING")
                speak_text(response_text, voice_name=self.tts_voice)
                from src.voice.audio_io import is_speaking
                for _ in range(40):
                    if is_speaking() or self._cancel_turn_event.is_set():
                        break
                    time.sleep(0.05)
                while is_speaking() and not self._cancel_turn_event.is_set():
                    time.sleep(0.05)
                if self._cancel_turn_event.is_set():
                    stop_speaking()
        finally:
            # Always restore engine to LISTENING and drain audio queues so user can speak immediately
            self.engine._drain_queue()
            self.engine._set_state("LISTENING")
            try:
                get_overlay().dismiss(delay_ms=15000)
            except Exception:
                pass



def get_voice_service() -> VoiceService:
    """Get or create singleton VoiceService instance."""
    global _global_voice_service
    with _service_lock:
        if _global_voice_service is None:
            _global_voice_service = VoiceService()
        return _global_voice_service


def main() -> None:
    """CLI entrypoint for running the voice service as a standalone daemon."""
    parser = argparse.ArgumentParser(description="Aether Standalone Voice Activation Daemon")
    parser.add_argument("--wake-word", default=None, help="Wake word to listen for (default: 'aether')")
    parser.add_argument("--threshold", type=float, default=None, help="Sensitivity threshold (0.0 to 1.0)")
    parser.add_argument("--no-tts", action="store_true", help="Disable spoken audio responses")
    args = parser.parse_args()

    service = VoiceService(
        wake_word=args.wake_word,
        threshold=args.threshold,
        tts_enabled=not args.no_tts,
    )

    print("=====================================================================")
    print("  AETHER LOCAL VOICE ACTIVATION DAEMON")
    print(f"  Wake Word: '{service.wake_word}' | Threshold: {service.threshold}")
    print(f"  Speech Output (TTS): {'Enabled' if service.tts_enabled else 'Disabled'}")
    print("  Listening... Say the wake word to speak. Press Ctrl+C to stop.")
    print("=====================================================================")

    service.start()
    try:
        while True:
            time.sleep(1.0)
    except (KeyboardInterrupt, SystemExit):
        print("\nStopping voice daemon...")
        service.stop()
        print("Voice daemon stopped.")


if __name__ == "__main__":
    main()
