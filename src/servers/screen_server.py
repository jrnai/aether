r"""Screen capture and active foreground window inspection server for Project Aether.

Provides native OS-level desktop visual perception without external cloud dependencies:
- Captures active desktop display via Win32 GDI / Pillow ImageGrab.
- Attaches thread to WinSta0\Default desktop station on Windows to guarantee capture in any thread.
- Automatically scales and compresses captures for fast, low-latency local VLM inference (Qwen2.5-VL).
- Inspects active foreground window title and process information for contextual awareness.
"""
from __future__ import annotations

import base64
import ctypes
import io
import logging
import sys
from typing import Any

from fastmcp import FastMCP
from PIL import Image, ImageGrab

logger = logging.getLogger("aether.screen")

mcp = FastMCP("ScreenVision")


def _attach_thread_to_desktop() -> bool:
    """Attach the calling thread to the interactive desktop station on Windows."""
    if sys.platform != "win32":
        return True

    try:
        user32 = ctypes.windll.user32
        hdesktop = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesktop:
            res = user32.SetThreadDesktop(hdesktop)
            return bool(res)
    except Exception as e:
        logger.debug("Failed to set thread desktop: %s", e)
    return False


def is_aether_window(title: str) -> bool:
    """Check if a window title belongs to Project Aether."""
    t = title.lower()
    return (
        "project aether" in t
        or "aether — desktop intelligence" in t
        or "aether console" in t
        or "127.0.0.1:8000" in t
        or "localhost:8000" in t
    )


def get_active_window_info() -> dict[str, Any]:
    """Retrieve title and metadata of the currently focused foreground window.

    If the focused window is Project Aether itself, also inspects the desktop Z-order
    to discover the underlying application window immediately beneath it.
    """
    if sys.platform != "win32":
        return {
            "title": "Desktop Environment",
            "process": "unknown",
            "platform": sys.platform,
        }

    try:
        _attach_thread_to_desktop()
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"title": "Desktop / Taskbar", "process": "explorer.exe"}

        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value.strip()
        else:
            title = "Untitled Window"

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        info: dict[str, Any] = {
            "title": title or "Desktop",
            "hwnd": str(hwnd),
            "pid": str(pid.value),
        }

        # If Aether is currently focused, discover the underlying application window in the Z-order
        if is_aether_window(title):
            info["is_aether"] = True
            next_hwnd = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT = 2
            while next_hwnd:
                if user32.IsWindowVisible(next_hwnd):
                    l = user32.GetWindowTextLengthW(next_hwnd)
                    if l > 0:
                        b = ctypes.create_unicode_buffer(l + 1)
                        user32.GetWindowTextW(next_hwnd, b, l + 1)
                        cand = b.value.strip()
                        if cand and not is_aether_window(cand) and cand not in (
                            "Program Manager",
                            "Settings",
                            "Default IME",
                            "MSCTFIME UI",
                            "Windows Input Experience",
                        ):
                            info["underlying_window"] = cand
                            info["underlying_hwnd"] = str(next_hwnd)
                            break
                next_hwnd = user32.GetWindow(next_hwnd, 2)

        return info
    except Exception as e:
        logger.debug("Error inspecting active window: %s", e)
        return {"title": "Desktop", "error": str(e)}


def capture_desktop_screen(
    max_dimension: int = 1280,
    quality: int = 85,
    include_window_info: bool = True,
) -> dict[str, Any]:
    """Capture the user's primary/active desktop display as an optimized base64 JPEG."""
    _attach_thread_to_desktop()

    try:
        try:
            img = ImageGrab.grab(all_screens=True)
        except Exception:
            img = ImageGrab.grab()

        orig_w, orig_h = img.size

        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        if orig_w > max_dimension or orig_h > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        cur_w, cur_h = img.size

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        raw_bytes = buf.getvalue()
        b64_str = base64.b64encode(raw_bytes).decode("ascii")

        win_info = get_active_window_info() if include_window_info else {}
        win_title = win_info.get("title", "Desktop")

        return {
            "status": "success",
            "image_base64": b64_str,
            "data_url": f"data:image/jpeg;base64,{b64_str}",
            "width": cur_w,
            "height": cur_h,
            "original_width": orig_w,
            "original_height": orig_h,
            "bytes_size": len(raw_bytes),
            "active_window": win_title,
            "active_window_details": win_info,
            "format": "jpeg",
        }
    except Exception as e:
        logger.exception("Desktop screen capture failed: %s", e)
        return {
            "status": "error",
            "message": f"Screen capture failed: {e}",
            "active_window": get_active_window_info().get("title", "Desktop"),
        }


@mcp.tool()
def capture_screen(max_dimension: int = 1280) -> dict[str, Any]:
    """Capture the user's active desktop screen and retrieve active foreground window title.

    Use this tool whenever the user asks 'what\'s on my screen', 'look at my screen',
    'read this error', 'summarize what I am looking at', or asks for help with an open window.
    """
    res = capture_desktop_screen(max_dimension=max_dimension)
    if res.get("status") == "success":
        win = res.get("active_window", "Desktop")
        w = res.get("width")
        h = res.get("height")
        return {
            "status": "success",
            "active_window": win,
            "resolution": f"{w}x{h}",
            "message": f"Screen captured successfully. Foreground Window: '{win}'. Resolution: {w}x{h}. Visual screenshot attached.",
            "image_base64": res.get("image_base64"),
        }
    return {
        "status": "error",
        "message": res.get("message", "Unable to capture desktop screen."),
    }


@mcp.tool()
def get_active_window() -> dict[str, str]:
    """Get the title and details of the currently focused foreground window on the user's desktop."""
    return get_active_window_info()


@mcp.tool()
def show_aether_dashboard() -> dict[str, Any]:
    """Bring the Aether desktop dashboard window to the foreground when explicitly requested by the user.

    Use this tool only when the user explicitly asks to 'show dashboard', 'open dashboard',
    'open app', 'bring window to front', or 'show aether'.
    """
    from src.voice.audio_io import bring_app_window_to_foreground

    success = bring_app_window_to_foreground()
    return {
        "status": "success" if success else "failed",
        "message": (
            "Aether dashboard brought to the foreground."
            if success
            else "Could not locate or bring Aether window to foreground."
        ),
    }
