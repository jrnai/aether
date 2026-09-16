"""Audio feedback and speech synthesis utilities for Project Aether."""
import logging
import re
import sys
import threading
from typing import Any

logger = logging.getLogger("aether.voice.audio_io")

_speech_lock = threading.Lock()
_is_speaking = False
_stop_speech_event = threading.Event()
_active_speaker: Any = None
_active_proc: Any = None


def is_speaking() -> bool:
    """Return True if TTS speech output is currently active."""
    global _is_speaking
    return _is_speaking


def stop_speaking() -> bool:
    """Immediately stop any active speech synthesis output and purge speech buffers."""
    global _is_speaking, _active_speaker, _active_proc
    _stop_speech_event.set()
    stopped = False

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.winmm.mciSendStringW("stop aether_tts", None, 0, None)
            ctypes.windll.winmm.mciSendStringW("close aether_tts", None, 0, None)
            stopped = True
        except Exception as e:
            logger.debug("Failed to stop MCI speech: %s", e)

    if _active_speaker is not None:
        try:
            # SVSFlagsAsync (1) | SVSFPurgeBeforeSpeak (2) = 3
            _active_speaker.Speak("", 3)
            stopped = True
        except Exception as e:
            logger.debug("Failed to purge SAPI speaker: %s", e)

    if _active_proc is not None:
        try:
            _active_proc.terminate()
            stopped = True
        except Exception:
            pass
        _active_proc = None

    _is_speaking = False
    return stopped


def play_wake_chime() -> None:
    """Play gentle asynchronous Windows chime when wake word is detected."""
    if sys.platform != "win32":
        return
    try:
        import winsound
        winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception as e:
        logger.debug("Failed to play wake chime: %s", e)


def play_ready_chime() -> None:
    """Play a short acknowledgment tone when speech capture completes."""
    if sys.platform != "win32":
        return
    try:
        import winsound
        winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception as e:
        logger.debug("Failed to play ready chime: %s", e)


def play_cancel_chime() -> None:
    """Play soft sound when speech capture times out or is cancelled."""
    if sys.platform != "win32":
        return
    try:
        import winsound
        winsound.PlaySound("SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception as e:
        logger.debug("Failed to play cancel chime: %s", e)


def clean_markdown_for_speech(text: str) -> str:
    """Strip markdown symbols, urls, code blocks, and formatting so speech is natural."""
    if not text:
        return ""
    # Remove XML-style tool calls and internal thinking tags
    cleaned = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</?(?:tool_call|think)>", "", cleaned, flags=re.IGNORECASE)
    # Remove code blocks
    cleaned = re.sub(r"```[\s\S]*?```", " [code block omitted] ", cleaned)
    # Remove inline code
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    # Replace markdown links [title](url) with title
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    # Remove images
    cleaned = re.sub(r"!\[[^\]]*\]\([^\)]+\)", "", cleaned)
    # Remove headers (###, ##, #)
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    # Remove bold/italic asterisks and underscores
    cleaned = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", cleaned)
    # Remove bullet markers (- or *)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    # Remove numbered list markers (1., 2.)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    # Normalize excess whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def speak_text(text: str, voice_name: str | None = None) -> bool:
    """Speak text out loud using natural neural TTS (with SAPI offline fallback).

    Thread-safe and sets the is_speaking flag to suppress acoustic feedback into the microphone.
    """
    global _is_speaking
    plain_text = clean_markdown_for_speech(text)
    if not plain_text:
        return False

    if sys.platform != "win32":
        logger.warning("TTS currently only supported on Windows.")
        return False

    def _speak_worker() -> None:
        global _is_speaking, _active_speaker, _active_proc
        with _speech_lock:
            if _stop_speech_event.is_set():
                _is_speaking = False
                return
            _is_speaking = True
            spoken = False
            try:
                # 1. First choice: High quality natural neural speech via edge-tts
                try:
                    import asyncio
                    import ctypes
                    import os
                    import tempfile
                    import time
                    import edge_tts
                    from src.config import get_config

                    target_voice = voice_name
                    if not target_voice:
                        try:
                            cfg = get_config()
                            target_voice = getattr(getattr(cfg, "voice", None), "tts_voice", "en-US-AriaNeural")
                        except Exception:
                            target_voice = "en-US-AriaNeural"

                    if not target_voice or not target_voice.endswith("Neural"):
                        target_voice = "en-US-AriaNeural"

                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_f:
                        tmp_audio_path = tmp_f.name

                    try:
                        comm = edge_tts.Communicate(plain_text, target_voice)
                        asyncio.run(comm.save(tmp_audio_path))

                        if not _stop_speech_event.is_set():
                            winmm = ctypes.windll.winmm
                            winmm.mciSendStringW("close aether_tts", None, 0, None)
                            open_cmd = f'open "{tmp_audio_path}" type mpegvideo alias aether_tts'
                            res = winmm.mciSendStringW(open_cmd, None, 0, None)
                            if res == 0:
                                winmm.mciSendStringW("play aether_tts", None, 0, None)
                                buf = ctypes.create_unicode_buffer(128)
                                while not _stop_speech_event.is_set():
                                    winmm.mciSendStringW("status aether_tts mode", buf, 128, None)
                                    if buf.value in ("stopped", ""):
                                        break
                                    time.sleep(0.05)
                                if _stop_speech_event.is_set():
                                    winmm.mciSendStringW("stop aether_tts", None, 0, None)
                                winmm.mciSendStringW("close aether_tts", None, 0, None)
                                spoken = True
                    finally:
                        if os.path.exists(tmp_audio_path):
                            try:
                                os.remove(tmp_audio_path)
                            except Exception:
                                pass
                except Exception as e:
                    logger.debug("Neural edge-tts speech failed (%s), falling back to Windows SAPI...", e)

                # 2. Offline fallback: Windows SAPI COM speaker
                if not spoken and not _stop_speech_event.is_set():
                    try:
                        import pythoncom
                        import win32com.client

                        pythoncom.CoInitialize()
                        try:
                            speaker = win32com.client.Dispatch("SAPI.SpVoice")
                            if voice_name and not voice_name.endswith("Neural"):
                                for v in speaker.GetVoices():
                                    if voice_name.lower() in v.GetDescription().lower():
                                        speaker.Voice = v
                                        break
                            _active_speaker = speaker
                            speaker.Speak(plain_text, 1)
                            while not _stop_speech_event.is_set():
                                if speaker.WaitUntilDone(50):
                                    break
                            if _stop_speech_event.is_set():
                                try:
                                    speaker.Speak("", 3)
                                except Exception:
                                    pass
                            spoken = True
                        finally:
                            _active_speaker = None
                            pythoncom.CoUninitialize()
                    except Exception as e:
                        logger.debug("win32com SAPI speech failed (%s), attempting PowerShell SpeechSynthesizer...", e)

                # 3. Last-resort fallback: PowerShell SpeechSynthesizer
                if not spoken and not _stop_speech_event.is_set():
                    try:
                        import subprocess
                        import time
                        escaped = plain_text.replace("'", "''")
                        cmd = [
                            "powershell",
                            "-NoProfile",
                            "-Command",
                            f"Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.Speak('{escaped}')",
                        ]
                        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        _active_proc = proc
                        try:
                            while proc.poll() is None:
                                if _stop_speech_event.is_set():
                                    proc.terminate()
                                    break
                                time.sleep(0.05)
                            spoken = True
                        finally:
                            _active_proc = None
                    except Exception as ex:
                        logger.error("PowerShell TTS speech also failed: %s", ex)
            finally:
                _is_speaking = False

    _stop_speech_event.clear()
    t = threading.Thread(target=_speak_worker, daemon=True, name="Aether-TTS-Speaker")
    t.start()
    return True


def bring_app_window_to_foreground() -> bool:
    """Restore and bring the Aether desktop window to the foreground."""
    if sys.platform != "win32":
        return False
    try:
        import subprocess

        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "$wshell = New-Object -ComObject WScript.Shell; "
                "$res = $wshell.AppActivate('Project Aether'); "
                "if (-not $res) { $null = $wshell.AppActivate('AETHER') }; "
                "exit 0"
            ),
        ]
        subprocess.run(cmd, capture_output=True, timeout=1.5)
        return True
    except Exception as e:
        logger.debug("Failed to bring window to front: %s", e)
        return False

