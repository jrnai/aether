"""Voice activation and speech processing package for Project Aether."""
from src.voice.audio_io import clean_markdown_for_speech, is_speaking, play_cancel_chime, play_ready_chime, play_wake_chime, speak_text

__all__ = [
    "clean_markdown_for_speech",
    "is_speaking",
    "play_wake_chime",
    "play_ready_chime",
    "play_cancel_chime",
    "speak_text",
]
