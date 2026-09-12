"""CalDAV protocol client for self-hosted and standards-compliant calendars.

Supports Nextcloud, Radicale, Fastmail, Apple Calendar, and generic CalDAV servers.
Adheres to Project Aether Specification 02: MCP Server Contracts (§3.2).
"""
import logging
import os
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger("aether.caldav")

try:
    import caldav
    from caldav.elements import dav
    CALDAV_AVAILABLE = True
except ImportError:
    caldav = None  # type: ignore
    CALDAV_AVAILABLE = False


class CalDAVManager:
    """Manages 2-way event synchronization with CalDAV servers."""

    def __init__(
        self,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        calendar_name: str | None = None,
    ) -> None:
        self.url = url or os.environ.get("CALENDAR_URL") or os.environ.get("CALDAV_URL")
        self.username = username or os.environ.get("CALENDAR_USER") or os.environ.get("CALDAV_USER")
        self.password = password or os.environ.get("CALENDAR_PASSWORD") or os.environ.get("CALDAV_PASSWORD")
        self.calendar_name = calendar_name or os.environ.get("CALDAV_CALENDAR_NAME")

        self._client: Any = None
        self._calendar: Any = None

    def is_configured(self) -> bool:
        """Return True if required CalDAV parameters are present in environment/config."""
        provider = os.environ.get("CALENDAR_PROVIDER", "").lower()
        if provider == "caldav":
            return bool(self.url and self.username and self.password)
        return bool(self.url and self.username and self.password)

    def _get_client(self) -> Any:
        if not CALDAV_AVAILABLE:
            raise RuntimeError("The 'caldav' Python package is not installed.")
        if self._client is None:
            if not self.url:
                raise ValueError("CalDAV URL is not configured.")
            self._client = caldav.DAVClient(
                url=self.url,
                username=self.username,
                password=self.password,
            )
        return self._client

    def get_calendar(self) -> Any:
        """Resolve the primary or named CalDAV calendar instance."""
        if self._calendar is not None:
            return self._calendar

        client = self._get_client()
        principal = client.principal()
        calendars = principal.calendars()

        if not calendars:
            raise RuntimeError("No CalDAV calendars found for this user account.")

        if self.calendar_name:
            for cal in calendars:
                name = getattr(cal, "name", "")
                if name and name.lower() == self.calendar_name.lower():
                    self._calendar = cal
                    return cal

        # Default to first calendar
        self._calendar = calendars[0]
        return self._calendar

    def fetch_events(self, start_dt: datetime, end_dt: datetime) -> list[dict[str, Any]]:
        """Fetch all calendar events occurring within a time interval."""
        if not self.is_configured():
            return []

        try:
            calendar = self.get_calendar()
            raw_events = calendar.search(start=start_dt, end=end_dt, event=True, expand=True)
            events: list[dict[str, Any]] = []

            for item in raw_events:
                try:
                    comp = item.icalendar_component
                    if comp.name != "VEVENT":
                        continue

                    uid = str(comp.get("uid", uuid.uuid4().hex))
                    summary = str(comp.get("summary", "Untitled Event"))
                    description = str(comp.get("description", ""))
                    location = str(comp.get("location", ""))

                    dtstart = comp.get("dtstart")
                    dtend = comp.get("dtend")

                    start_val = dtstart.dt if dtstart else start_dt
                    end_val = dtend.dt if dtend else end_dt

                    # Format to ISO string
                    start_str = start_val.isoformat() if hasattr(start_val, "isoformat") else str(start_val)
                    end_str = end_val.isoformat() if hasattr(end_val, "isoformat") else str(end_val)

                    events.append({
                        "id": uid,
                        "title": summary,
                        "start": start_str,
                        "end": end_str,
                        "location": location,
                        "description": description,
                    })
                except Exception as inner_e:
                    logger.debug("Failed to parse individual VEVENT: %s", inner_e)
                    continue

            return sorted(events, key=lambda x: x["start"])
        except Exception as e:
            logger.error("Failed to query CalDAV server: %s", e)
            return []

    def create_event(
        self,
        title: str,
        start_iso: str,
        end_iso: str,
        description: str = "",
        location: str = "",
    ) -> dict[str, Any]:
        """Create and publish a new event to the CalDAV calendar."""
        if not self.is_configured():
            return {"status": "error", "message": "CalDAV is not configured."}

        try:
            calendar = self.get_calendar()
            uid = f"caldav_{uuid.uuid4().hex[:12]}"

            # Construct clean iCalendar VCALENDAR text payload
            vcal_text = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Aether Desktop Agent//CalDAV Client//EN
BEGIN:VEVENT
UID:{uid}
SUMMARY:{title}
DESCRIPTION:{description}
LOCATION:{location}
DTSTART:{datetime.fromisoformat(start_iso.replace('Z', '+00:00')).strftime('%Y%m%dT%H%M%SZ')}
DTEND:{datetime.fromisoformat(end_iso.replace('Z', '+00:00')).strftime('%Y%m%dT%H%M%SZ')}
END:VEVENT
END:VCALENDAR"""

            event = calendar.save_event(vcal_text)
            return {
                "status": "success",
                "event_id": uid,
                "title": title,
                "start": start_iso,
                "end": end_iso,
                "message": f"Successfully created CalDAV event '{title}'.",
            }
        except Exception as e:
            logger.error("Failed to create CalDAV event: %s", e)
            return {"status": "error", "message": f"CalDAV event creation failed: {e}"}

    def delete_event(self, event_id: str) -> dict[str, Any]:
        """Delete an event from CalDAV calendar by UID."""
        if not self.is_configured():
            return {"status": "error", "message": "CalDAV is not configured."}

        try:
            calendar = self.get_calendar()
            # Search for event by UID
            event = calendar.event_by_uid(event_id)
            if event:
                event.delete()
                return {"status": "success", "message": f"Successfully deleted CalDAV event {event_id}."}
            return {"status": "error", "message": f"Event {event_id} not found in CalDAV."}
        except Exception as e:
            logger.error("Failed to delete CalDAV event %s: %s", event_id, e)
            return {"status": "error", "message": f"CalDAV event deletion failed: {e}"}
