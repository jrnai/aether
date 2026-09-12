"""Project Aether desktop notifications package."""
from src.notifications.toast import (
    notify_briefing_ready,
    notify_calendar_event,
    notify_urgent_email,
    send_toast,
)

__all__ = [
    "send_toast",
    "notify_briefing_ready",
    "notify_urgent_email",
    "notify_calendar_event",
]
