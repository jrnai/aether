"""Google Calendar client supporting OAuth 2.0 (Full 2-Way Sync) and private iCal feed."""
import json
import logging
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger("aether.google_calendar")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Google Calendar Event Colors (1 to 11)
GOOGLE_EVENT_COLORS = {
    "1": {"name": "Lavender", "hex": "#a4bdfc"},
    "2": {"name": "Sage", "hex": "#7ae7bf"},
    "3": {"name": "Grape", "hex": "#dbadff"},
    "4": {"name": "Flamingo", "hex": "#ff887c"},
    "5": {"name": "Banana", "hex": "#fbd75b"},
    "6": {"name": "Tangerine", "hex": "#ffb878"},
    "7": {"name": "Peacock", "hex": "#46d6db"},
    "8": {"name": "Graphite", "hex": "#e1e1e1"},
    "9": {"name": "Blueberry", "hex": "#5484ed"},
    "10": {"name": "Basil", "hex": "#51b749"},
    "11": {"name": "Tomato", "hex": "#dc2127"},
}

COLOR_NAME_TO_ID = {
    "lavender": "1",
    "light blue": "1",
    "pastel blue": "1",
    "sage": "2",
    "light green": "2",
    "lime": "2",
    "lime green": "2",
    "mint": "2",
    "grape": "3",
    "purple": "3",
    "violet": "3",
    "flamingo": "4",
    "pink": "4",
    "salmon": "4",
    "light red": "4",
    "banana": "5",
    "yellow": "5",
    "gold": "5",
    "tangerine": "6",
    "orange": "6",
    "peacock": "7",
    "cyan": "7",
    "teal": "7",
    "turquoise": "7",
    "graphite": "8",
    "gray": "8",
    "grey": "8",
    "blueberry": "9",
    "blue": "9",
    "dark blue": "9",
    "basil": "10",
    "green": "10",
    "dark green": "10",
    "tomato": "11",
    "red": "11",
    "crimson": "11",
    "dark red": "11",
}


def resolve_color_id(color: str | int | None) -> str | None:
    """Resolve a color name or number to a valid Google Calendar colorId ('1' to '11')."""
    if color is None:
        return None
    c_str = str(color).strip().lower()
    if c_str in COLOR_NAME_TO_ID:
        return COLOR_NAME_TO_ID[c_str]
    if c_str.isdigit() and 1 <= int(c_str) <= 11:
        return c_str
    return None


def get_data_dir() -> Path:
    """Return local data directory."""
    d = Path(os.environ.get("AETHER_DATA_DIR", "./data")).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


class GoogleCalendarManager:
    """Manages live synchronization with Google Calendar via OAuth 2.0 API or iCal feed."""

    def __init__(self, env_path: str | None = None) -> None:
        if env_path is not None:
            load_dotenv(dotenv_path=env_path, override=True)
        else:
            load_dotenv(override=False)

        data_dir = get_data_dir()
        self.token_path = Path(os.environ.get("GOOGLE_CALENDAR_TOKEN_PATH", str(data_dir / "calendar_token.json"))).resolve()
        self.credentials_path = Path(os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_PATH", "credentials.json")).resolve()
        self.ical_url = os.environ.get("GOOGLE_CALENDAR_ICAL_URL", "").strip()

    def is_oauth_configured(self) -> bool:
        """Check if OAuth client credentials file exists."""
        if self.credentials_path.exists():
            return True
        config_creds = Path("config/credentials.json")
        return config_creds.exists()

    def get_credentials_path(self) -> Path:
        """Return the resolved path to client credentials file."""
        if self.credentials_path.exists():
            return self.credentials_path
        config_creds = Path("config/credentials.json")
        if config_creds.exists():
            return config_creds
        return self.credentials_path

    def is_logged_in(self) -> bool:
        """Check if an active, valid OAuth token exists."""
        if not self.token_path.exists():
            return False
        try:
            creds = self.get_credentials()
            return creds is not None and creds.valid
        except Exception:
            return False

    def get_credentials(self) -> Any | None:
        """Load and refresh OAuth credentials from token file."""
        if not self.token_path.exists():
            return None

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials

            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired Google Calendar access token...")
                creds.refresh(Request())
                with open(self.token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            return creds
        except Exception as e:
            logger.warning("Failed to load/refresh Google Calendar credentials: %s", e)
            return None

    def get_service(self) -> Any | None:
        """Build Google Calendar v3 API service."""
        creds = self.get_credentials()
        if not creds:
            return None
        try:
            from googleapiclient.discovery import build
            return build("calendar", "v3", credentials=creds, cache_discovery=False)
        except Exception as e:
            logger.error("Failed to build Google Calendar service: %s", e)
            return None

    def fetch_events_api(self, start_dt: datetime, end_dt: datetime) -> list[dict[str, Any]]:
        """Fetch live events from Google Calendar API within a time window."""
        service = self.get_service()
        if not service:
            return []

        try:
            time_min_str = start_dt.isoformat()
            time_max_str = end_dt.isoformat()

            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=time_min_str,
                    timeMax=time_max_str,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            items = events_result.get("items", [])
            results: list[dict[str, Any]] = []

            for item in items:
                start = item.get("start", {})
                end = item.get("end", {})

                start_val = start.get("dateTime") or start.get("date") or ""
                end_val = end.get("dateTime") or end.get("date") or ""

                results.append({
                    "id": item.get("id", ""),
                    "title": item.get("summary", "No Title"),
                    "start": start_val,
                    "end": end_val,
                    "description": item.get("description", ""),
                    "location": item.get("location", ""),
                    "html_link": item.get("htmlLink", ""),
                    "color_id": item.get("colorId", ""),
                    "source": "google_calendar",
                })

            return results
        except Exception as e:
            logger.error("Error fetching events from Google Calendar API: %s", e)
            return []

    def fetch_events_ical(self, start_dt: datetime, end_dt: datetime) -> list[dict[str, Any]]:
        """Fetch live events from secret iCal URL within a time window."""
        if not self.ical_url:
            return []

        try:
            import requests
            from icalendar import Calendar

            res = requests.get(self.ical_url, timeout=12.0)
            if res.status_code != 200:
                logger.warning("iCal request returned status %s", res.status_code)
                return []

            cal = Calendar.from_ical(res.content)
            events: list[dict[str, Any]] = []

            for component in cal.walk():
                if component.name == "VEVENT":
                    dtstart = component.get("dtstart")
                    dtend = component.get("dtend")
                    if not dtstart:
                        continue

                    s_dt = dtstart.dt
                    if isinstance(s_dt, date) and not isinstance(s_dt, datetime):
                        s_dt = datetime.combine(s_dt, time.min).astimezone()
                    elif s_dt.tzinfo is None:
                        s_dt = s_dt.astimezone()

                    if dtend:
                        e_dt = dtend.dt
                        if isinstance(e_dt, date) and not isinstance(e_dt, datetime):
                            e_dt = datetime.combine(e_dt, time.min).astimezone()
                        elif e_dt.tzinfo is None:
                            e_dt = e_dt.astimezone()
                    else:
                        e_dt = s_dt + timedelta(hours=1)

                    if s_dt < end_dt and e_dt > start_dt:
                        events.append({
                            "id": f"ical_{str(component.get('uid', ''))[:20]}",
                            "title": str(component.get("summary", "No Title")),
                            "start": s_dt.isoformat(),
                            "end": e_dt.isoformat(),
                            "description": str(component.get("description", "")),
                            "location": str(component.get("location", "")),
                            "source": "google_ical",
                        })

            return sorted(events, key=lambda x: x["start"])
        except Exception as e:
            logger.warning("Failed to fetch/parse Google Calendar iCal feed: %s", e)
            return []

    def fetch_events(self, start_dt: datetime, end_dt: datetime) -> list[dict[str, Any]]:
        """Fetch live events preferring Google Calendar API, falling back to iCal feed."""
        if self.is_logged_in():
            events = self.fetch_events_api(start_dt, end_dt)
            if events:
                self._update_local_cache(events)
            return events

        if self.ical_url:
            events = self.fetch_events_ical(start_dt, end_dt)
            if events:
                self._update_local_cache(events)
            return events

        return []

    def get_primary_timezone(self) -> str:
        """Fetch and cache primary calendar timezone string."""
        if hasattr(self, "_primary_tz") and self._primary_tz:
            return self._primary_tz
        try:
            service = self.get_service()
            if service:
                cal = service.calendars().get(calendarId="primary").execute()
                self._primary_tz = cal.get("timeZone", "America/Toronto")
                return self._primary_tz
        except Exception:
            pass
        self._primary_tz = "America/Toronto"
        return self._primary_tz

    def create_event(
        self,
        title: str,
        start_iso: str,
        end_iso: str,
        description: str = "",
        location: str = "",
        recurrence: list[str] | str | None = None,
    ) -> dict[str, Any]:
        """Create a new event on live Google Calendar via API with optional recurrence rules."""
        if not self.is_logged_in():
            return {
                "status": "error",
                "message": "Google Calendar API is not authenticated. Run 'python -m src.tools.login_google_calendar' to log in.",
            }

        service = self.get_service()
        if not service:
            return {
                "status": "error",
                "message": "Failed to connect to Google Calendar API service.",
            }

        try:
            tz = self.get_primary_timezone()
            event_body: dict[str, Any] = {
                "summary": title,
                "start": {"dateTime": start_iso, "timeZone": tz},
                "end": {"dateTime": end_iso, "timeZone": tz},
            }
            if description:
                event_body["description"] = description
            if location:
                event_body["location"] = location
            if recurrence:
                event_body["recurrence"] = [recurrence] if isinstance(recurrence, str) else list(recurrence)

            created = (
                service.events()
                .insert(calendarId="primary", body=event_body)
                .execute()
            )

            new_record = {
                "id": created.get("id", ""),
                "title": title,
                "start": start_iso,
                "end": end_iso,
                "description": description,
                "location": location,
                "html_link": created.get("htmlLink", ""),
                "source": "google_calendar",
            }
            self._update_local_cache([new_record])

            return {
                "status": "success",
                "event_id": created.get("id"),
                "html_link": created.get("htmlLink", ""),
                "title": title,
                "start": start_iso,
                "end": end_iso,
                "message": f"Successfully created event '{title}' on your Google Calendar.",
            }
        except Exception as e:
            logger.error("Failed to insert event into Google Calendar: %s", e)
            return {
                "status": "error",
                "message": f"Google Calendar API insert failed: {e}",
            }

    def create_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Create multiple events on live Google Calendar in batch."""
        created_events = []
        errors = []
        for evt in events:
            title = evt.get("title") or evt.get("summary") or evt.get("name") or "Scheduled Event"
            start_iso = evt.get("start_iso") or evt.get("start") or ""
            end_iso = evt.get("end_iso") or evt.get("end") or ""
            desc = evt.get("description", "")
            loc = evt.get("location", "")
            rec = evt.get("recurrence")
            res = self.create_event(
                title=title,
                start_iso=start_iso,
                end_iso=end_iso,
                description=desc,
                location=loc,
                recurrence=rec,
            )
            if res.get("status") == "success":
                created_events.append(res)
            else:
                errors.append({"title": title, "error": res.get("message")})

        return {
            "status": "success" if created_events else "error",
            "created_count": len(created_events),
            "events": created_events,
            "errors": errors,
            "message": f"Successfully created {len(created_events)} events on Google Calendar." if created_events else "Failed to create events.",
        }

    def delete_event(self, event_id: str) -> dict[str, Any]:
        """Delete an event from live Google Calendar via API."""
        if not self.is_logged_in():
            return {
                "status": "error",
                "message": "Google Calendar API is not authenticated.",
            }

        service = self.get_service()
        if not service:
            return {
                "status": "error",
                "message": "Failed to connect to Google Calendar service.",
            }

        try:
            service.events().delete(calendarId="primary", eventId=event_id).execute()
            self._remove_from_local_cache(event_id)
            return {
                "status": "success",
                "event_id": event_id,
                "message": f"Successfully deleted event '{event_id}' from Google Calendar.",
            }
        except Exception as e:
            logger.error("Failed to delete event '%s' from Google Calendar: %s", event_id, e)
            return {
                "status": "error",
                "message": f"Google Calendar API delete failed: {e}",
            }

    def update_event(
        self,
        event_id: str,
        title: str | None = None,
        start_iso: str | None = None,
        end_iso: str | None = None,
        color: str | int | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> dict[str, Any]:
        """Update or patch an existing event on Google Calendar (e.g. change color, title, time, location)."""
        if not self.is_logged_in():
            return {
                "status": "error",
                "message": "Google Calendar API is not authenticated.",
            }

        service = self.get_service()
        if not service:
            return {
                "status": "error",
                "message": "Failed to connect to Google Calendar service.",
            }

        try:
            patch_body: dict[str, Any] = {}
            if title is not None:
                patch_body["summary"] = title.strip()
            if description is not None:
                patch_body["description"] = description.strip()
            if location is not None:
                patch_body["location"] = location.strip()

            color_id = resolve_color_id(color)
            if color_id is not None:
                patch_body["colorId"] = color_id

            if start_iso:
                tz = self.get_primary_timezone()
                patch_body["start"] = {"dateTime": start_iso, "timeZone": tz}
            if end_iso:
                tz = self.get_primary_timezone()
                patch_body["end"] = {"dateTime": end_iso, "timeZone": tz}

            if not patch_body:
                return {"status": "error", "message": "No update fields provided."}

            updated = (
                service.events()
                .patch(calendarId="primary", eventId=event_id, body=patch_body)
                .execute()
            )

            color_meta = GOOGLE_EVENT_COLORS.get(updated.get("colorId", ""), {})
            color_name = color_meta.get("name", updated.get("colorId", "Default"))

            updated_record = {
                "id": updated.get("id", event_id),
                "title": updated.get("summary", title or "Event"),
                "start": updated.get("start", {}).get("dateTime", start_iso or ""),
                "end": updated.get("end", {}).get("dateTime", end_iso or ""),
                "color_id": updated.get("colorId", ""),
                "description": updated.get("description", description or ""),
                "location": updated.get("location", location or ""),
                "html_link": updated.get("htmlLink", ""),
                "source": "google_calendar",
            }
            self._update_local_cache([updated_record])

            return {
                "status": "success",
                "event_id": event_id,
                "title": updated_record["title"],
                "color_id": updated_record["color_id"],
                "color_name": color_name,
                "message": f"Successfully updated event '{updated_record['title']}' (Color: {color_name}).",
            }
        except Exception as e:
            logger.error("Failed to patch Google Calendar event '%s': %s", event_id, e)
            return {
                "status": "error",
                "message": f"Google Calendar API update failed: {e}",
            }

    def update_events(
        self,
        query: str | None = None,
        color: str | int | None = None,
        event_ids: list[str] | None = None,
        time_window_days: int = 14,
    ) -> dict[str, Any]:
        """Update multiple events matching a query or list of IDs (ideal for bulk color coding or scheduling adjustments)."""
        if not self.is_logged_in():
            return {
                "status": "error",
                "message": "Google Calendar API is not authenticated.",
            }

        now = datetime.now().astimezone()
        start_dt = now - timedelta(days=2)
        end_dt = now + timedelta(days=time_window_days)

        all_events = self.fetch_events(start_dt, end_dt)
        target_events: list[dict[str, Any]] = []

        if event_ids:
            target_ids_set = set(event_ids)
            target_events = [e for e in all_events if e.get("id") in target_ids_set]
        elif query:
            q_lower = query.strip().lower()
            for e in all_events:
                t = e.get("title", "").lower()
                d = e.get("description", "").lower()
                l = e.get("location", "").lower()
                if q_lower in t or q_lower in d or q_lower in l:
                    target_events.append(e)
        else:
            target_events = all_events

        if not target_events:
            return {
                "status": "error",
                "message": f"No events found matching query '{query or ''}' in the next {time_window_days} days.",
            }

        updated_count = 0
        errors = []
        updated_titles = []
        resolved_color = resolve_color_id(color)

        # Deduplicate recurring series to parent event IDs so we color whole recurring series efficiently
        seen_base_ids = set()
        unique_targets = []
        for evt in target_events:
            eid = evt.get("id")
            if not eid:
                continue
            base_id = eid.split("_")[0] if "_" in eid and not eid.startswith("evt_") else eid
            if base_id in seen_base_ids:
                continue
            seen_base_ids.add(base_id)
            unique_targets.append((base_id, evt.get("title", base_id)))

        for base_id, title in unique_targets:
            res = self.update_event(event_id=base_id, color=resolved_color)
            if res.get("status") == "success":
                updated_count += 1
                updated_titles.append(title)
            else:
                errors.append({"title": title, "error": res.get("message")})

        color_meta = GOOGLE_EVENT_COLORS.get(resolved_color, {}) if resolved_color else {}
        color_name = color_meta.get("name", str(color or "Default"))

        return {
            "status": "success" if updated_count > 0 else "error",
            "updated_count": updated_count,
            "color": color_name,
            "updated_events": updated_titles,
            "errors": errors,
            "message": f"Successfully updated {updated_count} events to {color_name}." if updated_count > 0 else "Failed to update events.",
        }

    def _update_local_cache(self, new_events: list[dict[str, Any]]) -> None:
        """Cache live Google events locally in data/calendar_events.json for offline resilience."""
        try:
            data_dir = get_data_dir()
            store_file = data_dir / "calendar_events.json"
            existing: list[dict[str, Any]] = []
            if store_file.exists():
                with open(store_file, encoding="utf-8") as f:
                    existing = json.load(f)

            existing_map = {e.get("id"): e for e in existing if e.get("id")}
            for evt in new_events:
                if evt.get("id"):
                    existing_map[evt["id"]] = evt

            combined = list(existing_map.values())
            with open(store_file, "w", encoding="utf-8") as f:
                json.dump(combined, f, indent=2)
        except Exception as e:
            logger.warning("Could not update local calendar cache: %s", e)

    def _remove_from_local_cache(self, event_id: str) -> None:
        """Remove deleted event from local cache."""
        try:
            data_dir = get_data_dir()
            store_file = data_dir / "calendar_events.json"
            if not store_file.exists():
                return
            with open(store_file, encoding="utf-8") as f:
                existing = json.load(f)
            remaining = [e for e in existing if e.get("id") != event_id]
            with open(store_file, "w", encoding="utf-8") as f:
                json.dump(remaining, f, indent=2)
        except Exception as e:
            logger.warning("Could not remove event from local cache: %s", e)
