"""Unit tests for voice activation engine, audio utilities, and service integration."""
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from src.config import AetherConfig, VoiceConfig
from src.voice.audio_io import (
    bring_app_window_to_foreground,
    clean_markdown_for_speech,
    is_speaking,
    stop_speaking,
)
from src.voice.engine import VoiceEngine
from src.voice.service import VoiceService
from src.web.server import app


def test_voice_config_defaults() -> None:
    """Verify VoiceConfig defaults and presence in AetherConfig."""
    vc = VoiceConfig()
    assert vc.enabled is False
    assert vc.wake_word == "aether"
    assert vc.threshold == 0.5
    assert vc.stt_model == "base.en"
    assert vc.tts_enabled is True
    assert vc.tts_voice == "en-US-AriaNeural"
    assert vc.silence_timeout_seconds == 1.2
    assert vc.max_recording_seconds == 15.0

    cfg = AetherConfig()
    assert hasattr(cfg, "voice")
    assert cfg.voice.wake_word == "aether"


def test_clean_markdown_for_speech() -> None:
    """Verify clean_markdown_for_speech strips markdown syntax and code blocks."""
    raw = (
        "# Weather Report\n\n"
        "Here is the forecast for **Kingston**:\n"
        "- Current temp: `22°C`\n"
        "- Source: [Environment Canada](https://weather.gc.ca)\n\n"
        "```python\nprint('hello')\n```\n"
        "<think>internal thoughts</think>\n"
        "<tool_call>{\"name\": \"calendar_delete_event\"}</tool_call>\n"
        "Have a great day!"
    )
    cleaned = clean_markdown_for_speech(raw)

    assert "#" not in cleaned
    assert "**" not in cleaned
    assert "`" not in cleaned
    assert "https://" not in cleaned
    assert "<tool_call>" not in cleaned
    assert "<think>" not in cleaned
    assert "calendar_delete_event" not in cleaned
    assert "internal thoughts" not in cleaned
    assert "Environment Canada" in cleaned
    assert "code block omitted" in cleaned
    assert "Have a great day!" in cleaned


def test_wake_word_key_mapping() -> None:
    """Verify that user-friendly wake words map to openWakeWord model keys."""
    eng0 = VoiceEngine(wake_word="aether")
    assert eng0._get_oww_key() == "aether"

    eng0b = VoiceEngine(wake_word="hey aether")
    assert eng0b._get_oww_key() == "aether"

    eng1 = VoiceEngine(wake_word="hey jarvis")
    assert eng1._get_oww_key() == "hey_jarvis"

    eng2 = VoiceEngine(wake_word="Alexa")
    assert eng2._get_oww_key() == "alexa"

    eng3 = VoiceEngine(wake_word="jarvis")
    assert eng3._get_oww_key() == "hey_jarvis"


def test_voice_engine_lifecycle() -> None:
    """Verify state transitions and pause/resume logic."""
    states: list[str] = []
    eng = VoiceEngine(
        wake_word="hey jarvis",
        on_state_change=lambda s: states.append(s),
    )
    assert eng.state == "IDLE"

    eng.pause()
    assert eng.state == "PAUSED"

    eng.resume()
    assert eng.state == "LISTENING"

    eng.stop()
    assert eng.state == "IDLE"
    assert "PAUSED" in states
    assert "LISTENING" in states


def test_voice_service_status_and_toggle() -> None:
    """Verify VoiceService get_status and toggle controls."""
    with patch.object(VoiceEngine, "start") as mock_start, patch.object(VoiceEngine, "stop") as mock_stop:
        srv = VoiceService(wake_word="hey jarvis", threshold=0.6)
        status = srv.get_status()

        assert status["running"] is False
        assert status["wake_word"] == "hey jarvis"
        assert status["threshold"] == 0.6
        assert status["tts_enabled"] is True

        new_state = srv.toggle()
        assert new_state is True
        assert srv.is_running is True
        mock_start.assert_called_once()

        new_state2 = srv.toggle()
        assert new_state2 is False
        assert srv.is_running is False
        mock_stop.assert_called_once()


def test_voice_service_listen_now() -> None:
    """Verify listen_now triggers engine and starts service if stopped."""
    with patch.object(VoiceEngine, "start") as mock_start, patch.object(VoiceEngine, "trigger_listen_now") as mock_listen:
        srv = VoiceService()
        assert srv.is_running is False
        srv.listen_now()
        assert srv.is_running is True
        mock_start.assert_called_once()
        mock_listen.assert_called_once()


def test_api_voice_endpoints() -> None:
    """Verify GET /api/voice/status, POST /api/voice/toggle, and POST /api/voice/listen."""
    client = TestClient(app)

    # 1. Test status endpoint
    resp = client.get("/api/voice/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "running" in data
    assert "wake_word" in data

    # 2. Test toggle endpoint with explicit enabled=False
    with patch("src.voice.service.VoiceEngine.start"), patch("src.voice.service.VoiceEngine.stop"):
        toggle_resp = client.post("/api/voice/toggle", json={"enabled": False})
        assert toggle_resp.status_code == 200
        tdata = toggle_resp.json()
        assert tdata["status"] == "success"
        assert tdata["running"] is False

    # 3. Test listen endpoint
    with patch("src.voice.service.VoiceService.listen_now") as mock_listen_now:
        listen_resp = client.post("/api/voice/listen")
        assert listen_resp.status_code == 200
        ldata = listen_resp.json()
        assert ldata["status"] == "success"
        assert "Listening" in ldata["message"]
        mock_listen_now.assert_called_once()


def test_bring_app_window_to_foreground() -> None:
    """Verify bring_app_window_to_foreground runs without error."""
    with patch("subprocess.run") as mock_run:
        res = bring_app_window_to_foreground()
        assert res is True
        mock_run.assert_called_once()


def test_voice_service_event_emission() -> None:
    """Verify VoiceService subscriber registration and event broadcast."""
    import queue

    srv = VoiceService()
    test_q: queue.Queue = queue.Queue()

    srv.subscribe(test_q)
    assert test_q in srv._subscribers

    srv.emit_event("test_event", {"hello": "world"})
    event = test_q.get_nowait()
    assert event["type"] == "test_event"
    assert event["hello"] == "world"

    srv.unsubscribe(test_q)
    assert test_q not in srv._subscribers


@pytest.mark.asyncio
async def test_api_voice_events_sse() -> None:
    """Verify GET /api/voice/events streams initial snapshot event."""
    import json
    from starlette.requests import Request
    from src.web.server import api_voice_events

    scope = {"type": "http", "method": "GET", "path": "/api/voice/events", "headers": []}
    async def receive():
        return {"type": "http.disconnect"}

    req = Request(scope, receive)
    response = await api_voice_events(req)
    assert response.media_type == "text/event-stream"

    first_chunk = await anext(response.body_iterator)
    assert first_chunk.startswith("data: ")
    payload = json.loads(first_chunk[6:].strip())
    assert payload["type"] == "snapshot"
    assert "running" in payload
    assert "wake_word" in payload


def test_stop_speaking() -> None:
    """Verify stop_speaking sets event, purges SAPI speaker, and resets is_speaking."""
    import src.voice.audio_io as aio

    mock_speaker = MagicMock()
    mock_proc = MagicMock()
    aio._active_speaker = mock_speaker
    aio._active_proc = mock_proc
    aio._is_speaking = True

    res = aio.stop_speaking()
    assert res is True
    assert aio.is_speaking() is False
    mock_speaker.Speak.assert_called_once_with("", 3)
    mock_proc.terminate.assert_called_once()
    assert aio._active_proc is None


def test_voice_engine_interrupt() -> None:
    """Verify VoiceEngine.interrupt stops speech and invokes on_interrupt callback."""
    interrupted = False

    def on_int():
        nonlocal interrupted
        interrupted = True

    eng = VoiceEngine(wake_word="hey jarvis", on_interrupt=on_int)
    with patch("src.voice.engine.stop_speaking") as mock_stop_speak:
        eng.interrupt()
        mock_stop_speak.assert_called_once()
        assert interrupted is True


def test_voice_service_interrupt() -> None:
    """Verify VoiceService.interrupt increments turn_id, sets cancel event, and emits event."""
    import queue

    srv = VoiceService()
    test_q: queue.Queue = queue.Queue()
    srv.subscribe(test_q)

    initial_turn = srv._turn_id
    with patch("src.voice.audio_io.stop_speaking") as mock_stop_speak:
        srv.interrupt()
        mock_stop_speak.assert_called_once()
        assert srv._turn_id == initial_turn + 1
        assert srv._cancel_turn_event.is_set()

        event = test_q.get_nowait()
        assert event["type"] == "interrupt"
        assert event["turn_id"] == srv._turn_id

    srv.unsubscribe(test_q)


def test_api_voice_interrupt() -> None:
    """Verify POST /api/voice/interrupt triggers interrupt and returns updated status."""
    client = TestClient(app)
    with patch("src.voice.service.VoiceService.interrupt") as mock_int:
        resp = client.post("/api/voice/interrupt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "interrupted" in data["message"]
        mock_int.assert_called_once()


def test_voice_engine_interrupt_event_aborts_recording() -> None:
    """Verify VoiceEngine._handle_wake_event stops immediately when _interrupt_event is set."""
    eng = VoiceEngine()
    eng._interrupt_event.set()
    # Should exit immediately without hanging or running long timeouts
    with patch("src.voice.engine.bring_app_window_to_foreground"), \
         patch("src.voice.engine.play_wake_chime"), \
         patch("src.voice.engine.play_cancel_chime"):
        eng._handle_wake_event()
    assert eng.state == "LISTENING"
    assert not eng._is_handling_wake.locked()


def test_voice_service_on_speech_interrupted_cleans_up() -> None:
    """Verify VoiceService._on_user_speech restores LISTENING state when turn is interrupted."""
    srv = VoiceService()
    srv.tts_enabled = False
    srv._cancel_turn_event.set()
    srv._on_user_speech("hello there")
    assert srv.engine.state == "LISTENING"


def test_voice_engine_pop_window_on_wake_default_false() -> None:
    """Verify pop_window_on_wake defaults to False and prevents window pop-up on wake."""
    eng = VoiceEngine()
    assert eng.pop_window_on_wake is False
    eng._interrupt_event.set()

    with patch("src.voice.engine.bring_app_window_to_foreground") as mock_bring, \
         patch("src.voice.engine.play_wake_chime"), \
         patch("src.voice.engine.play_cancel_chime"):
        eng._handle_wake_event()
        mock_bring.assert_not_called()


def test_voice_engine_pop_window_on_wake_enabled() -> None:
    """Verify pop_window_on_wake=True brings window to front when explicitly enabled."""
    eng = VoiceEngine(pop_window_on_wake=True)
    assert eng.pop_window_on_wake is True
    eng._interrupt_event.set()

    with patch("src.voice.engine.bring_app_window_to_foreground") as mock_bring, \
         patch("src.voice.engine.play_wake_chime"), \
         patch("src.voice.engine.play_cancel_chime"):
        eng._handle_wake_event()
        mock_bring.assert_called_once()


def test_desktop_overlay_lifecycle() -> None:
    """Verify DesktopOverlay methods queue commands properly."""
    from src.voice.overlay import get_overlay
    ov = get_overlay()
    assert ov is not None

    ov.show("RECORDING")
    ov.set_transcript("hello world")
    ov.set_answer("test answer")
    ov.show_timeout()
    ov.dismiss(delay_ms=5000)
    ov.hide()
    # If no exceptions were raised, command queuing works cleanly
