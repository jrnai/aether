"""Floating desktop overlay for voice activation feedback.

A small always-on-top tkinter window that appears in the top-right corner
when the wake word is detected. Invisible to screen capture via
SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE).
"""
import logging
import queue
import sys
import threading
import time
import tkinter as tk
from typing import Any

logger = logging.getLogger("aether.voice.overlay")

# Win32 constant: makes window invisible to PrintWindow / BitBlt / ImageGrab
WDA_EXCLUDEFROMCAPTURE = 0x00000011

# Visual constants
_WIDTH = 350
_PADDING = 20
_BG = "#18181B"
_BG_DARK = "#09090B"
_PRIMARY = "#38BDF8"
_PRIMARY_DIM = "#0C4A6E"
_TEXT_MAIN = "#F4F4F5"
_TEXT_MUTED = "#A1A1AA"
_TEXT_DIM = "#71717A"
_FONT_FAMILY = "Segoe UI"


class DesktopOverlay:
    """Transparent always-on-top overlay window for voice state feedback."""

    def __init__(self) -> None:
        self._root: tk.Tk | None = None
        self._ready = threading.Event()
        self._cmd_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._thread = threading.Thread(target=self._run_mainloop, daemon=True, name="Aether-OverlayThread")
        self._thread.start()
        self._ready.wait(timeout=5.0)

    # ── public API (thread-safe, callable from any thread) ──────────────

    def show(self, state: str = "LISTENING") -> None:
        """Make overlay visible with given state."""
        self._send("show", state)

    def set_state(self, state: str) -> None:
        """Update state label and dot animation."""
        self._send("set_state", state)

    def set_transcript(self, text: str) -> None:
        """Display user's spoken text."""
        self._send("set_transcript", text)

    def set_answer(self, text: str) -> None:
        """Display AI response text."""
        self._send("set_answer", text)

    def show_timeout(self) -> None:
        """Display helpful feedback when no speech was heard."""
        self._send("timeout", None)

    def dismiss(self, delay_ms: int = 15000) -> None:
        """Schedule auto-hide after delay."""
        self._send("dismiss", delay_ms)

    def hide(self) -> None:
        """Immediately hide the overlay."""
        self._send("hide", None)

    # ── internal ────────────────────────────────────────────────────────

    def _send(self, cmd: str, arg: Any) -> None:
        self._cmd_queue.put((cmd, arg))
        if self._root:
            try:
                self._root.event_generate("<<Cmd>>", when="tail")
            except Exception:
                pass

    def _run_mainloop(self) -> None:
        """Build the tkinter UI and run its event loop (daemon thread)."""
        root = tk.Tk()
        self._root = root
        root.title("Aether Overlay")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.95)
        root.configure(bg=_BG)

        # Position: top-right corner
        sw = root.winfo_screenwidth()
        root.geometry(f"{_WIDTH}x60+{sw - _WIDTH - _PADDING}+{_PADDING}")

        self._is_hovered = False
        self._current_state = "IDLE"
        self._scroll_active = False
        self._scroll_job: str | None = None
        self._scroll_duration = 5.0
        self._scroll_elapsed = 0.0
        self._scroll_start_time = 0.0
        self._user_scroll_pause_until = 0.0

        # ── widgets ──
        self._frame = tk.Frame(root, bg=_BG, padx=12, pady=8)
        self._frame.pack(fill="both", expand=True)

        # Header row: dot + label + actions
        header = tk.Frame(self._frame, bg=_BG)
        header.pack(fill="x", anchor="w")

        self._dot = tk.Canvas(header, width=12, height=12, bg=_BG, highlightthickness=0)
        self._dot_id = self._dot.create_oval(2, 2, 10, 10, fill=_PRIMARY, outline="")
        self._dot.pack(side="left", padx=(0, 8))

        self._state_label = tk.Label(
            header, text="Listening…", fg=_PRIMARY, bg=_BG,
            font=(_FONT_FAMILY, 10, "bold"), anchor="w",
        )
        self._state_label.pack(side="left", fill="x", expand=True)

        # Header action buttons (Open App & Close)
        btn_box = tk.Frame(header, bg=_BG)
        btn_box.pack(side="right")

        self._open_btn = tk.Label(
            btn_box, text="Open App ↗", fg=_PRIMARY, bg=_BG,
            font=(_FONT_FAMILY, 8, "bold"), cursor="hand2", padx=4,
        )
        self._open_btn.pack(side="left", padx=(0, 6))
        self._open_btn.bind("<Button-1>", lambda _e: self._on_open_app())

        self._close_btn = tk.Label(
            btn_box, text="✕", fg=_TEXT_DIM, bg=_BG,
            font=(_FONT_FAMILY, 9), cursor="hand2", padx=4,
        )
        self._close_btn.pack(side="right")
        self._close_btn.bind("<Button-1>", lambda _e: self._do_hide())
        self._close_btn.bind("<Enter>", lambda _e: self._close_btn.config(fg=_TEXT_MAIN))
        self._close_btn.bind("<Leave>", lambda _e: self._close_btn.config(fg=_TEXT_DIM))

        # Transcript line
        self._transcript_label = tk.Label(
            self._frame, text="", fg=_TEXT_MUTED, bg=_BG,
            font=(_FONT_FAMILY, 9), anchor="w", justify="left", wraplength=_WIDTH - 40,
        )

        # Answer text widget (smooth scrolling, untruncated)
        self._answer_text = tk.Text(
            self._frame,
            bg=_BG,
            fg=_TEXT_MAIN,
            font=(_FONT_FAMILY, 9),
            wrap="word",
            bd=0,
            highlightthickness=0,
            relief="flat",
            padx=0,
            pady=0,
            cursor="arrow",
            takefocus=0,
        )
        self._answer_text.bind("<Button-1>", lambda _e: self._on_open_app())
        self._answer_label = self._answer_text

        # Pulse animation state
        self._pulse_on = True
        self._pulse_job: str | None = None
        self._dismiss_job: str | None = None

        # Hover-to-keep-open bindings
        def _on_enter(_e):
            self._is_hovered = True
            if self._dismiss_job and self._root:
                self._root.after_cancel(self._dismiss_job)
                self._dismiss_job = None

        def _on_leave(_e):
            self._is_hovered = False
            if self._current_state in ("SPEAKING", "IDLE", "TIMEOUT"):
                self._do_dismiss(6000)

        for w in (root, self._frame, header, btn_box, self._dot, self._state_label, self._open_btn, self._close_btn, self._transcript_label, self._answer_text):
            w.bind("<Enter>", _on_enter)
            w.bind("<Leave>", _on_leave)

        for w in (root, self._frame, header, self._transcript_label, self._answer_text):
            w.bind("<MouseWheel>", self._on_mousewheel)

        # Apply WDA_EXCLUDEFROMCAPTURE so screen capture doesn't see the overlay
        root.update_idletasks()
        self._apply_capture_exclusion(root)

        # Bind command processing
        root.bind("<<Cmd>>", lambda _e: self._process_commands())

        # Queue polling loop for robust event delivery even when withdrawn
        def _poll_queue():
            self._process_commands()
            if self._root:
                self._root.after(80, _poll_queue)

        _poll_queue()

        # Start hidden
        root.withdraw()
        self._ready.set()
        root.mainloop()

    def _on_open_app(self) -> None:
        """Bring the main Aether window to the foreground."""
        try:
            from src.voice.audio_io import bring_app_window_to_foreground
            bring_app_window_to_foreground()
        except Exception as e:
            logger.debug("Failed to bring app window to front: %s", e)

    def _apply_capture_exclusion(self, root: tk.Tk) -> None:
        """Make the overlay invisible to screen capture (Windows 10 2004+)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(root.wm_frame(), 16)
            result = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            if result:
                logger.info("Overlay excluded from screen capture (WDA_EXCLUDEFROMCAPTURE).")
            else:
                err = ctypes.windll.kernel32.GetLastError()
                logger.warning("SetWindowDisplayAffinity failed (error %d). Overlay may appear in screenshots.", err)
        except Exception as e:
            logger.debug("Could not apply capture exclusion: %s", e)

    def _process_commands(self) -> None:
        """Drain the command queue and apply updates (runs on tkinter thread)."""
        root = self._root
        if not root:
            return
        while not self._cmd_queue.empty():
            try:
                cmd, arg = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            if cmd == "show":
                self._do_show(arg)
            elif cmd == "set_state":
                self._do_set_state(arg)
            elif cmd == "set_transcript":
                self._do_set_transcript(arg)
            elif cmd == "set_answer":
                self._do_set_answer(arg)
            elif cmd == "timeout":
                self._do_timeout()
            elif cmd == "dismiss":
                self._do_dismiss(arg)
            elif cmd == "hide":
                self._do_hide()

    def _do_show(self, state: str) -> None:
        root = self._root
        if not root:
            return
        # Cancel pending dismiss and active scrolling
        if self._dismiss_job:
            root.after_cancel(self._dismiss_job)
            self._dismiss_job = None
        self._stop_autoscroll()
        self._is_hovered = False
        # Reset text
        self._transcript_label.config(text="")
        self._transcript_label.pack_forget()
        self._answer_text.config(state="normal")
        self._answer_text.delete("1.0", "end")
        self._answer_text.config(state="disabled", fg=_TEXT_MAIN)
        self._answer_text.pack_forget()
        # Resize to compact
        sw = root.winfo_screenwidth()
        root.geometry(f"{_WIDTH}x60+{sw - _WIDTH - _PADDING}+{_PADDING}")
        self._do_set_state(state)
        root.deiconify()
        root.lift()
        self._start_pulse()

    def _do_set_state(self, state: str) -> None:
        self._current_state = state
        labels = {
            "LISTENING": "Listening…",
            "RECORDING": "Listening to you…",
            "TRANSCRIBING": "Processing…",
            "PROCESSING": "Thinking…",
            "SPEAKING": "Aether Answer",
            "IDLE": "Ready",
            "TIMEOUT": "Didn't catch that",
        }
        self._state_label.config(text=labels.get(state, state), fg=_PRIMARY if state != "TIMEOUT" else _TEXT_MUTED)
        if state in ("LISTENING", "RECORDING", "TRANSCRIBING", "PROCESSING"):
            self._start_pulse()
        else:
            self._stop_pulse()

        if state == "SPEAKING":
            self._start_autoscroll()
        else:
            self._stop_autoscroll()

    def _do_set_transcript(self, text: str) -> None:
        if not text:
            return
        display = text if len(text) <= 120 else text[:117] + "…"
        self._transcript_label.config(text=f'"{display}"')
        self._transcript_label.pack(fill="x", anchor="w", pady=(4, 0))
        self._resize_to_fit()

    def _do_set_answer(self, text: str) -> None:
        if not text:
            return
        self._stop_autoscroll()
        self._answer_text.config(state="normal")
        self._answer_text.delete("1.0", "end")
        self._answer_text.insert("1.0", text)
        self._answer_text.config(state="disabled", fg=_TEXT_MAIN)

        # Dynamically size visible height up to 9 lines for comfortable desktop HUD
        est_lines = sum(max(1, (len(line) + 38) // 40) for line in text.splitlines()) or 1
        visible_lines = max(1, min(est_lines, 9))
        self._answer_text.config(height=visible_lines)
        self._answer_text.pack(fill="x", anchor="w", pady=(4, 0))
        self._answer_text.yview_moveto(0.0)
        self._resize_to_fit()

        if self._current_state == "SPEAKING":
            self._start_autoscroll()

    def _do_timeout(self) -> None:
        self._stop_pulse()
        self._stop_autoscroll()
        self._current_state = "TIMEOUT"
        self._state_label.config(text="Didn't catch that", fg=_TEXT_MUTED)
        msg = "Tap or say 'Aether' to try again, or click 'Open App ↗'."
        self._answer_text.config(state="normal")
        self._answer_text.delete("1.0", "end")
        self._answer_text.insert("1.0", msg)
        self._answer_text.config(state="disabled", fg=_TEXT_MUTED, height=2)
        self._answer_text.pack(fill="x", anchor="w", pady=(4, 0))
        self._answer_text.yview_moveto(0.0)
        self._resize_to_fit()
        if not self._is_hovered:
            self._do_dismiss(5000)

    def _do_dismiss(self, delay_ms: int) -> None:
        root = self._root
        if not root:
            return
        if self._dismiss_job:
            root.after_cancel(self._dismiss_job)
            self._dismiss_job = None
        # If user is hovering mouse over overlay, do not auto-dismiss!
        if self._is_hovered:
            return
        self._dismiss_job = root.after(delay_ms, self._do_hide)

    def _do_hide(self) -> None:
        self._stop_pulse()
        self._stop_autoscroll()
        if self._dismiss_job and self._root:
            self._root.after_cancel(self._dismiss_job)
            self._dismiss_job = None
        if self._root:
            self._root.withdraw()

    def _on_mousewheel(self, event: Any) -> None:
        """Allow user to manually scroll with mouse wheel and pause autoscroll."""
        if hasattr(self, "_answer_text") and self._answer_text:
            try:
                delta = getattr(event, "delta", 0)
                if delta:
                    self._answer_text.yview_scroll(int(-1 * (delta / 120)), "units")
                    # Pause autoscroll for 3 seconds when user manually scrolls
                    self._user_scroll_pause_until = time.monotonic() + 3.0
            except Exception:
                pass

    def _start_autoscroll(self) -> None:
        self._stop_autoscroll()
        if not self._root:
            return

        text = self._answer_text.get("1.0", "end").strip()
        if not text:
            return

        est_lines = sum(max(1, (len(line) + 38) // 40) for line in text.splitlines()) or 1
        # If text fits in the visible height (up to 9 lines), no scrolling needed
        if est_lines <= 9:
            return

        words = len(text.split())
        # TTS speaks at ~2.5 words/sec; scale duration so text moves with speech
        duration = max(4.0, (words / 2.5) + 0.5)

        self._scroll_active = True
        self._scroll_duration = duration
        self._scroll_elapsed = 0.0
        self._scroll_start_time = time.monotonic()
        self._user_scroll_pause_until = 0.0
        self._scroll_job = self._root.after(50, self._scroll_tick)

    def _stop_autoscroll(self) -> None:
        self._scroll_active = False
        if self._scroll_job and self._root:
            self._root.after_cancel(self._scroll_job)
            self._scroll_job = None

    def _scroll_tick(self) -> None:
        if not self._scroll_active or not self._root:
            return

        now = time.monotonic()
        # Pause advancing scroll if mouse is hovering over overlay or user manually scrolled
        if self._is_hovered or now < self._user_scroll_pause_until:
            self._scroll_start_time = now - self._scroll_elapsed
            self._scroll_job = self._root.after(80, self._scroll_tick)
            return

        elapsed = now - self._scroll_start_time
        self._scroll_elapsed = elapsed
        progress = min(1.0, elapsed / self._scroll_duration)

        try:
            y0, y1 = self._answer_text.yview()
            f_view = y1 - y0
            if f_view < 1.0:
                target = progress * (1.0 - f_view)
                self._answer_text.yview_moveto(target)
        except Exception:
            pass

        if progress < 1.0 and self._current_state == "SPEAKING":
            self._scroll_job = self._root.after(50, self._scroll_tick)
        else:
            self._scroll_active = False
            self._scroll_job = None

    def _resize_to_fit(self) -> None:
        """Let tkinter auto-size the height based on content."""
        root = self._root
        if not root:
            return
        root.update_idletasks()
        h = self._frame.winfo_reqheight() + 4
        h = max(60, min(h, 350))
        sw = root.winfo_screenwidth()
        root.geometry(f"{_WIDTH}x{h}+{sw - _WIDTH - _PADDING}+{_PADDING}")

    def _start_pulse(self) -> None:
        if self._pulse_job:
            return  # already pulsing
        self._pulse_on = True
        self._pulse_tick()

    def _stop_pulse(self) -> None:
        if self._pulse_job and self._root:
            self._root.after_cancel(self._pulse_job)
            self._pulse_job = None
        self._dot.itemconfig(self._dot_id, fill=_PRIMARY)

    def _pulse_tick(self) -> None:
        color = _PRIMARY if self._pulse_on else _PRIMARY_DIM
        self._dot.itemconfig(self._dot_id, fill=color)
        self._pulse_on = not self._pulse_on
        if self._root:
            self._pulse_job = self._root.after(600, self._pulse_tick)


# ── singleton ───────────────────────────────────────────────────────────

_overlay: DesktopOverlay | None = None
_overlay_lock = threading.Lock()


def get_overlay() -> DesktopOverlay:
    """Get or create the singleton desktop overlay."""
    global _overlay
    with _overlay_lock:
        if _overlay is None:
            _overlay = DesktopOverlay()
        return _overlay
