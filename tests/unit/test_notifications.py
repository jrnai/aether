"""Unit tests for desktop notifications module."""
from unittest.mock import MagicMock, patch

from src.notifications.toast import (
    notify_briefing_ready,
    notify_calendar_event,
    notify_urgent_email,
    send_toast,
)


def test_send_toast_non_windows() -> None:
    """Verify that send_toast logs and returns False on non-Windows platforms."""
    with patch("platform.system", return_value="Linux"):
        result = send_toast(title="Test", message="Hello")
        assert result is False


def test_send_toast_windows_success() -> None:
    """Verify send_toast properly calls winotify when available."""
    with patch("platform.system", return_value="Windows"), \
         patch("winotify.Notification") as mock_notif_cls:
        mock_instance = MagicMock()
        mock_notif_cls.return_value = mock_instance

        res = send_toast(title="Aether Test", message="Hello from test")
        assert res is True
        mock_notif_cls.assert_called_once()
        mock_instance.show.assert_called_once()


def test_send_toast_handles_exception() -> None:
    """Verify send_toast catches and handles exceptions gracefully."""
    with patch("platform.system", return_value="Windows"), \
         patch("winotify.Notification", side_effect=RuntimeError("COM failure")):
        res = send_toast(title="Fail Test", message="Error")
        assert res is False


def test_notification_helpers() -> None:
    """Verify helper notification methods dispatch with appropriate format."""
    with patch("src.notifications.toast.send_toast", return_value=True) as mock_toast:
        res1 = notify_briefing_ready("2026-09-05", "3 meetings today")
        assert res1 is True
        mock_toast.assert_called_with(title="🌅 Morning Briefing Ready (2026-09-05)", message="3 meetings today")

        res2 = notify_urgent_email("dean@ntu.edu.sg", "Faculty Meeting")
        assert res2 is True
        assert "dean@ntu.edu.sg" in mock_toast.call_args[1]["message"]

        res3 = notify_calendar_event("Project Review", "14:00")
        assert res3 is True
        assert "14:00" in mock_toast.call_args[1]["message"]
