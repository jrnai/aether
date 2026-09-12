"""Native Windows Desktop Notifications for Project Aether using winotify."""
import logging
import platform

logger = logging.getLogger("aether.notifications")


def send_toast(
    title: str,
    message: str,
    app_id: str = "Project Aether",
    icon_path: str = "",
) -> bool:
    """Send a native Windows Toast notification via winotify.

    Gracefully falls back to logging on non-Windows platforms or if errors occur.
    """
    if platform.system() != "Windows":
        logger.info("[Notification] %s: %s", title, message)
        return False

    try:
        from winotify import Notification

        toast = Notification(
            app_id=app_id,
            title=title[:64],
            msg=message[:256],
            icon=icon_path if icon_path else "",
        )
        toast.show()
        logger.debug("Toast notification dispatched: %s", title)
        return True
    except Exception as e:
        logger.warning("Failed to show toast notification '%s': %s", title, e)
        return False


def notify_briefing_ready(date_str: str, snippet: str = "") -> bool:
    """Dispatch a notification that the morning briefing is ready."""
    title = f"🌅 Morning Briefing Ready ({date_str})"
    msg = snippet if snippet else "Your schedule, inbox highlights, and focus windows are prepared."
    return send_toast(title=title, message=msg)


def notify_urgent_email(sender: str, subject: str) -> bool:
    """Dispatch an alert for a high-priority incoming email."""
    title = "📬 High-Priority Email"
    msg = f"From: {sender}\nSubject: {subject}"
    return send_toast(title=title, message=msg)


def notify_calendar_event(title: str, start_time: str) -> bool:
    """Dispatch a reminder for an upcoming calendar event."""
    header = "⏰ Upcoming Calendar Event"
    msg = f"{title} starting at {start_time}"
    return send_toast(title=header, message=msg)
