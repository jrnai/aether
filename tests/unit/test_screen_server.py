"""Unit tests for Project Aether screen vision and active window inspection service."""
from unittest.mock import patch
from PIL import Image

from src.servers.screen_server import (
    capture_desktop_screen,
    capture_screen,
    get_active_window,
    get_active_window_info,
    is_aether_window,
    show_aether_dashboard,
)
from src.agent.loop import detect_intent_domains, get_tool_domain


def test_get_active_window_info():
    """Verify that active foreground window info returns a valid dict with title."""
    info = get_active_window_info()
    assert isinstance(info, dict)
    assert "title" in info
    assert isinstance(info["title"], str)
    assert len(info["title"]) > 0


def test_capture_desktop_screen_real_or_mock():
    """Verify desktop screen capture returns a base64 encoded JPEG with dimensions."""
    res = capture_desktop_screen(max_dimension=800, quality=80)
    assert res.get("status") == "success"
    assert "image_base64" in res
    assert len(res["image_base64"]) > 100
    assert res.get("data_url", "").startswith("data:image/jpeg;base64,")
    assert res["width"] > 0
    assert res["height"] > 0
    assert max(res["width"], res["height"]) <= 800
    assert "active_window" in res


def test_capture_desktop_screen_aspect_ratio_constraint():
    """Verify thumbnail resizing respects the max_dimension boundary."""
    # Create a mock 1920x1080 image
    mock_img = Image.new("RGB", (1920, 1080), color=(100, 150, 200))
    with patch("PIL.ImageGrab.grab", return_value=mock_img):
        res = capture_desktop_screen(max_dimension=640)
        assert res.get("status") == "success"
        assert res["width"] == 640
        assert res["height"] == 360
        assert res["original_width"] == 1920
        assert res["original_height"] == 1080


def test_capture_desktop_screen_graceful_error_handling():
    """Verify that if ImageGrab fails, error is safely caught and returned."""
    with patch("PIL.ImageGrab.grab", side_effect=RuntimeError("GDI subsystem offline")):
        res = capture_desktop_screen()
        assert res.get("status") == "error"
        assert "GDI subsystem offline" in res.get("message", "")


def test_capture_screen_mcp_tool():
    """Verify the FastMCP capture_screen tool returns expected structure."""
    mock_img = Image.new("RGB", (1280, 720), color=(50, 50, 50))
    with patch("PIL.ImageGrab.grab", return_value=mock_img):
        tool_res = capture_screen(max_dimension=1000)
        assert tool_res.get("status") == "success"
        assert "Foreground Window" in tool_res.get("message", "")
        assert "resolution" in tool_res
        assert tool_res.get("image_base64") is not None


def test_get_active_window_mcp_tool():
    """Verify FastMCP get_active_window tool returns window metadata."""
    info = get_active_window()
    assert isinstance(info, dict)
    assert "title" in info


def test_intent_routing_screen_and_vision():
    """Verify that visual and screen queries are routed to screen_and_vision domain."""
    queries = [
        "what is on my screen right now?",
        "look at my screen and tell me what you see",
        "can you see my monitor display?",
        "read the error on my screen",
        "inspect active window",
        "what am i looking at?",
    ]
    for q in queries:
        domains = detect_intent_domains(q)
        assert "screen_and_vision" in domains, f"Failed for query: {q}"


def test_tool_domain_mapping_screen():
    """Verify tool names map to screen_and_vision domain."""
    assert get_tool_domain("capture_screen") == "screen_and_vision"
    assert get_tool_domain("get_active_window") == "screen_and_vision"
    assert get_tool_domain("show_aether_dashboard") == "screen_and_vision"


def test_is_aether_window():
    """Verify detection of Aether window titles vs external application windows."""
    assert is_aether_window("Project Aether — Desktop Intelligence") is True
    assert is_aether_window("Project Aether - Google Chrome") is True
    assert is_aether_window("Aether Console - Desktop Automation Backend") is True
    assert is_aether_window("http://127.0.0.1:8000") is True
    assert is_aether_window("Visual Studio Code - main.py") is False
    assert is_aether_window("Google Chrome - Wikipedia") is False


def test_show_aether_dashboard_tool():
    """Verify show_aether_dashboard invokes bring_app_window_to_foreground."""
    with patch("src.voice.audio_io.bring_app_window_to_foreground", return_value=True):
        res = show_aether_dashboard()
        assert res["status"] == "success"
        assert "foreground" in res["message"]


def test_intent_routing_dashboard_keywords():
    """Verify dashboard focus queries route to screen_and_vision domain."""
    assert "screen_and_vision" in detect_intent_domains("show dashboard")
    assert "screen_and_vision" in detect_intent_domains("open app")
    assert "screen_and_vision" in detect_intent_domains("bring window to front")
