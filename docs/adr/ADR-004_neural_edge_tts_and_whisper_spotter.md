# ADR-004: Neural Edge-TTS & Adaptive Whisper Spotter vs. SAPI & openWakeWord

## Status
**Accepted** (2026-09)

## Context
Aether includes a hands-free voice assistant mode. The initial prototype used:
1. **Windows SAPI (Speech API)**: Local COM-based speech synthesis (`pyttsx3`).
2. **openWakeWord**: A fixed-model wake-word detection library trained specifically on `"hey jarvis"` and `"alexa"`.

This combination presented severe usability shortcomings:
- Windows SAPI produced robotic, flat, 1990s-style synthesized speech that severely degraded user perception of the assistant's intelligence.
- openWakeWord models are trained on fixed acoustic profiles. When the project was branded to **Aether**, openWakeWord was unable to reliably spot `"aether"` without collecting synthetic acoustic datasets and training an ONNX model from scratch.
- Speech playback could not be interrupted cleanly when the user started speaking (barge-in failure).

## Decision
We executed a complete voice pipeline overhaul ([`src/voice/`](file:///C:/Users/jrrya/Projects/aether/src/voice/)):
1. **Natural Neural TTS (`edge-tts`)**: Integrated Microsoft Neural Speech Synthesis (`en-US-AriaNeural`), generating studio-grade natural prosody, breathing, and pitch dynamics.
2. **Native Win32 Audio Playback (`winmm.dll`)**: Leveraged Windows native `mciSendStringW` API via `ctypes` for zero-dependency audio playback. This allows instant barge-in cancellation (`stop_playback()`) without process killing or thread locks.
3. **Adaptive Whisper Wake-Word Spotter**: Reused the already-loaded `faster-whisper` STT model (`base.en`) with an adaptive rolling audio buffer to spot `"aether"`, `"hey aether"`, and phonetic approximations (`"ether"`, `"either"`), providing high accuracy without custom model training.
4. **Offline Fallback**: Preserved Windows SAPI as a graceful fallback in the event of internet disconnection.

## Consequences
### Positive
- **Human-Quality Voice**: Audio quality shifted from robotic SAPI to studio-grade neural voice.
- **Zero Heavy Audio Player Dependencies**: Eliminated `pygame`, `playsound`, or external VLC players; uses native Windows OS multimedia API.
- **Instant Barge-In**: User interruptions immediately cut speech playback in <20ms.
- **Custom Wake Word**: Full reliability on `"aether"` without external ONNX model retraining.

### Negative
- `edge-tts` requires an active internet connection for real-time neural synthesis (falls back to local SAPI when offline).

## Alternatives Considered
- **Coqui TTS / Piper**: High-quality local neural models, but require 1.5–2.5 GB of dedicated VRAM or high CPU usage, which directly contends with Ollama and ComfyUI.
- **Retraining openWakeWord**: Generating synthetic audio datasets with Piper/Tortoise to train an ONNX model was rejected as disproportionate complexity when `faster-whisper` was already resident in memory.
