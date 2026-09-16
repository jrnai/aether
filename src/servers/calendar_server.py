"""FastMCP server for calendar operations (free/busy, scheduling, listing events)."""
import json
import os
import re
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from src.servers.caldav_client import CalDAVManager
from src.servers.google_calendar_client import GoogleCalendarManager

mcp = FastMCP("CalendarService")


def get_calendar_store_path() -> Path:
    """Return the path to the local calendar JSON/ICS store."""
    data_dir = Path(os.environ.get("AETHER_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "calendar_events.json"


def load_events() -> list[dict[str, Any]]:
    """Load events from local persistent store."""
    store_file = get_calendar_store_path()
    if not store_file.exists():
        return []

    try:
        with open(store_file, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


_EVENTS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_EVENTS_CACHE_TTL: float = 60.0  # 60 seconds TTL


def invalidate_events_cache() -> None:
    """Clear in-memory calendar events cache."""
    global _EVENTS_CACHE
    _EVENTS_CACHE.clear()


def save_events(events: list[dict[str, Any]]) -> None:
    """Save events to local persistent store."""
    invalidate_events_cache()
    store_file = get_calendar_store_path()
    with open(store_file, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)


def _parse_iso(iso_str: str) -> datetime:
    """Parse ISO-8601 or relative date/time string into timezone-aware datetime."""
    clean = iso_str.strip()
    if not clean:
        return datetime.now().astimezone()

    # Pre-normalize dot-separated time notation often produced by STT engines (e.g. "11.30 pm" -> "11:30 pm")
    clean = re.sub(
        r"\b(\d{1,2})\.(\d{2})(?:\s*(am|pm))?\b",
        lambda m: f"{m.group(1)}:{m.group(2)}" + (f" {m.group(3)}" if m.group(3) else ""),
        clean,
        flags=re.IGNORECASE,
    )

    # 1. Standard ISO format
    try:
        norm = clean.replace("Z", "+00:00")
        dt = datetime.fromisoformat(norm)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt
    except Exception:
        pass

    now = datetime.now().astimezone()
    clean_lower = clean.lower()

    # 2. Check for relative day markers: today, tonight, tomorrow
    target_date = now.date()
    is_relative_day = False
    time_str = clean

    if "tomorrow" in clean_lower:
        target_date = now.date() + timedelta(days=1)
        time_str = re.sub(r"\btomorrow\b", "", clean, flags=re.IGNORECASE).strip()
        is_relative_day = True
    elif "today" in clean_lower or "tonight" in clean_lower:
        target_date = now.date()
        time_str = re.sub(r"\b(today|tonight)\b", "", clean, flags=re.IGNORECASE).strip()
        is_relative_day = True

    if is_relative_day:
        time_str = re.sub(r"^(at|on)\s+", "", time_str, flags=re.IGNORECASE).strip()
        if not time_str:
            return datetime.combine(target_date, time(0, 0)).replace(tzinfo=now.tzinfo)
        try:
            from dateutil import parser
            parsed = parser.parse(time_str, default=datetime.combine(target_date, time(0, 0)))
            return datetime.combine(target_date, parsed.time()).replace(tzinfo=now.tzinfo)
        except Exception:
            pass

    # 3. Check for day of week relative strings (e.g. "Monday 10:30 AM", "Wed 2:30 PM")
    days_map = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1, "tues": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
    }

    for day_name, target_weekday in days_map.items():
        if clean_lower.startswith(day_name):
            monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            target_date = monday + timedelta(days=target_weekday)
            time_part = clean[len(day_name):].strip().lstrip("-:, ")
            if time_part:
                for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M", "%I %p", "%I%p"):
                    try:
                        parsed_t = datetime.strptime(time_part, fmt).time()
                        return datetime.combine(target_date.date(), parsed_t).replace(tzinfo=now.tzinfo)
                    except ValueError:
                        continue
            return target_date

    # 4. Fallback to dateutil if available
    try:
        from dateutil import parser
        parsed = parser.parse(clean, default=datetime.combine(now.date(), time(0, 0)))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=now.tzinfo)
        return parsed
    except Exception:
        pass

    raise ValueError(f"Unable to parse datetime string: '{iso_str}'")


@mcp.tool()
def list_events(
    start_iso: str | None = None,
    end_iso: str | None = None,
    start: str | None = None,
    end: str | None = None,
    date: str | None = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """List calendar events within an ISO-8601 time window (defaults to full current day)."""
    now = datetime.now().astimezone()

    if date:
        date_clean = date.strip()
        start_dt = _parse_iso(date_clean).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = _parse_iso(end_iso or end) if (end_iso or end) else start_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        start_raw = start_iso or start
        end_raw = end_iso or end
        if start_raw:
            start_dt = _parse_iso(start_raw)
            if len(start_raw.strip()) <= 10:
                start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = _parse_iso(end_raw) if end_raw else start_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            # Defaults to full current day
            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = _parse_iso(end_raw) if end_raw else start_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    start_dt = start_dt.replace(microsecond=0)
    end_dt = end_dt.replace(microsecond=0)

    def _enrich_event(evt: dict[str, Any]) -> dict[str, Any]:
        item = dict(evt)
        start_val = item.get("start") or item.get("start_time") or item.get("start_iso") or ""
        try:
            edt = _parse_iso(str(start_val))
            item["date"] = edt.strftime("%Y-%m-%d")
            item["day_of_week"] = edt.strftime("%A")
            item["is_today"] = (edt.date() == now.date())
        except Exception:
            pass
        return item

    # 1. Attempt live Google Calendar fetch (API or iCal) if configured
    gcal_manager = GoogleCalendarManager()
    if gcal_manager.is_logged_in() or gcal_manager.ical_url:
        import time as _time
        now_ts = _time.time()
        cache_key = f"gcal_{start_dt.isoformat()}_{end_dt.isoformat()}"
        if not force_refresh and cache_key in _EVENTS_CACHE:
            cached_ts, cached_list = _EVENTS_CACHE[cache_key]
            if now_ts - cached_ts < _EVENTS_CACHE_TTL:
                return [dict(e) for e in cached_list]

        # On cold start, serve local disk cache instantly (<1ms) and sync in background
        if not force_refresh and cache_key not in _EVENTS_CACHE:
            cached_disk = load_events()
            if cached_disk:
                matching_disk = []
                for evt in cached_disk:
                    try:
                        evt_start = _parse_iso(evt.get("start") or evt.get("start_time", ""))
                        evt_end = _parse_iso(evt.get("end") or evt.get("end_time", ""))
                        if evt_start < end_dt and evt_end > start_dt:
                            matching_disk.append(_enrich_event(evt))
                    except Exception:
                        continue
                if matching_disk:
                    results = sorted(matching_disk, key=lambda x: x["start"])
                    _EVENTS_CACHE[cache_key] = (now_ts, results)
                    import threading
                    def _bg_sync():
                        try:
                            bg_live = gcal_manager.fetch_events(start_dt, end_dt)
                            if bg_live:
                                _EVENTS_CACHE[cache_key] = (_time.time(), [_enrich_event(e) for e in sorted(bg_live, key=lambda x: x["start"])])
                        except Exception:
                            pass
                    threading.Thread(target=_bg_sync, daemon=True, name="gcal-bg-sync").start()
                    return results

        live_events = gcal_manager.fetch_events(start_dt, end_dt)
        if live_events:
            results = [_enrich_event(e) for e in sorted(live_events, key=lambda x: x["start"])]
            _EVENTS_CACHE[cache_key] = (now_ts, results)
            return results

    # 2. Attempt CalDAV fetch if configured
    caldav_mgr = CalDAVManager()
    if caldav_mgr.is_configured():
        import time as _time
        now_ts = _time.time()
        cache_key = f"caldav_{start_dt.isoformat()}_{end_dt.isoformat()}"
        if not force_refresh and cache_key in _EVENTS_CACHE:
            cached_ts, cached_list = _EVENTS_CACHE[cache_key]
            if now_ts - cached_ts < _EVENTS_CACHE_TTL:
                return [dict(e) for e in cached_list]

        caldav_events = caldav_mgr.fetch_events(start_dt, end_dt)
        if caldav_events:
            results = [_enrich_event(e) for e in sorted(caldav_events, key=lambda x: x["start"])]
            _EVENTS_CACHE[cache_key] = (now_ts, results)
            return results

    # 3. Fallback to local persistent store (instant 0.05ms disk read)
    events = load_events()
    matching: list[dict[str, Any]] = []
    for evt in events:
        try:
            evt_start = _parse_iso(evt["start"])
            evt_end = _parse_iso(evt["end"])
            # Overlaps interval if evt_start < end_dt and evt_end > start_dt
            if evt_start < end_dt and evt_end > start_dt:
                matching.append(_enrich_event(evt))
        except Exception:
            continue

    return sorted(matching, key=lambda x: x["start"])


@mcp.tool()
def get_free_slots(
    date_iso: str | None = None,
    date: str | None = None,
    duration_minutes: int = 30,
    duration: int | None = None,
    buffer_minutes: int = 30,
    buffer: int | None = None,
    work_start_hour: int = 9,
    work_end_hour: int = 18,
    events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Scan busy calendar intervals for a specific day and return open available time slots.

    Enforces a mandatory buffer (default 30 minutes) before and after every scheduled
    event/time block so no focus session is placed within 30 minutes of any calendar event.
    """
    date_iso = date_iso or date
    if duration is not None:
        duration_minutes = duration
    if buffer is not None:
        buffer_minutes = buffer

    buffer_delta = timedelta(minutes=max(0, buffer_minutes))

    now = datetime.now().astimezone()
    target_dt = _parse_iso(date_iso) if date_iso else now
    target_date = target_dt.date()

    day_start = datetime.combine(target_date, time(work_start_hour, 0)).replace(tzinfo=target_dt.tzinfo)
    day_end = datetime.combine(target_date, time(work_end_hour, 0)).replace(tzinfo=target_dt.tzinfo)

    search_start_dt = day_start - buffer_delta
    search_end_dt = day_end + buffer_delta

    if events is not None:
        # Filter pre-fetched events to active day + buffer window
        target_events = []
        for evt in events:
            try:
                evt_start = _parse_iso(evt["start"])
                evt_end = _parse_iso(evt["end"])
                if evt_start < search_end_dt and evt_end > search_start_dt:
                    target_events.append(evt)
            except Exception:
                continue
    else:
        # Fetch events on that day, expanding the search window by buffer_delta so events ending near
        # day_start or starting near day_end whose buffer extends into the workday are also captured.
        target_events = list_events(
            start_iso=search_start_dt.isoformat(),
            end_iso=search_end_dt.isoformat(),
        )

    # Build busy intervals expanded by the buffer before and after
    busy_spans: list[tuple[datetime, datetime]] = []
    for evt in target_events:
        try:
            evt_start = _parse_iso(evt["start"])
            evt_end = _parse_iso(evt["end"])
            # Expand by buffer before and after
            b_start = evt_start - buffer_delta
            b_end = evt_end + buffer_delta
            # Clamp to the active workday boundaries
            s = max(day_start, b_start)
            e = min(day_end, b_end)
            if s < e:
                busy_spans.append((s, e))
        except Exception:
            continue

    # Merge overlapping or touching busy intervals
    merged_spans: list[tuple[datetime, datetime]] = []
    for s, e in sorted(busy_spans, key=lambda x: x[0]):
        if not merged_spans:
            merged_spans.append((s, e))
        else:
            prev_s, prev_e = merged_spans[-1]
            if s <= prev_e:
                merged_spans[-1] = (prev_s, max(prev_e, e))
            else:
                merged_spans.append((s, e))

    # Find free gaps
    free_slots: list[dict[str, Any]] = []
    current_cursor = day_start
    min_delta = timedelta(minutes=duration_minutes)

    for b_start, b_end in merged_spans:
        if b_start > current_cursor:
            gap = b_start - current_cursor
            if gap >= min_delta:
                free_slots.append({
                    "start": current_cursor.strftime("%H:%M"),
                    "end": b_start.strftime("%H:%M"),
                    "duration_minutes": int(gap.total_seconds() / 60),
                })
        if b_end > current_cursor:
            current_cursor = b_end

    if current_cursor < day_end:
        gap = day_end - current_cursor
        if gap >= min_delta:
            free_slots.append({
                "start": current_cursor.strftime("%H:%M"),
                "end": day_end.strftime("%H:%M"),
                "duration_minutes": int(gap.total_seconds() / 60),
            })

    return free_slots



@mcp.tool()
def create_event(
    title: str = "",
    start_iso: str = "",
    end_iso: str = "",
    description: str = "",
    location: str = "",
    recurrence: list[str] | str | None = None,
    events: list[dict[str, Any]] | None = None,
    summary: str | None = None,
    name: str | None = None,
    event: str | None = None,
    task: str | None = None,
    text: str | None = None,
    start: str | None = None,
    end: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    startTime: str | None = None,
    endTime: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    duration_minutes: int | None = None,
    duration: int | None = None,
    desc: str | None = None,
    details: str | None = None,
    loc: str | None = None,
    room: str | None = None,
) -> dict[str, Any]:
    """Schedule a new calendar event. (Mutating action requiring user confirmation)."""
    # If caller passed a batch of events, route directly to create_events
    if events and isinstance(events, list):
        return create_events(events=events)

    title = title or summary or name or event or task or text or "Scheduled Event"
    start_iso = start_iso or start or start_time or startTime or start_date or ""
    end_iso = end_iso or end or end_time or endTime or end_date or ""
    description = description or desc or details or ""
    location = location or loc or room or ""

    if not start_iso:
        return {
            "status": "error",
            "message": "Missing start time for calendar event.",
        }

    dur = duration_minutes if duration_minutes is not None else duration if duration is not None else 30

    try:
        start_dt = _parse_iso(start_iso)
        if end_iso:
            end_dt = _parse_iso(end_iso)
            if end_dt <= start_dt:
                # Handle midnight crossover (e.g. 11:30 PM to 12:00 AM)
                if end_dt + timedelta(days=1) > start_dt and (end_dt + timedelta(days=1) - start_dt) <= timedelta(hours=14):
                    end_dt += timedelta(days=1)
                else:
                    return {
                        "status": "error",
                        "message": "End time must be strictly after start time.",
                    }
        else:
            end_dt = start_dt + timedelta(minutes=dur)

        # 1. Attempt live Google Calendar creation if authenticated
        gcal_warning = None
        gcal_manager = GoogleCalendarManager()
        if gcal_manager.is_logged_in():
            live_res = gcal_manager.create_event(
                title=title.strip(),
                start_iso=start_dt.isoformat(),
                end_iso=end_dt.isoformat(),
                description=description.strip(),
                location=location.strip(),
                recurrence=recurrence,
            )
            if live_res.get("status") == "success":
                return live_res
            gcal_warning = f"Google Calendar API sync failed ({live_res.get('message', 'unknown error')})."
        elif gcal_manager.token_path.exists() or gcal_manager.is_oauth_configured():
            gcal_warning = (
                "Google OAuth authorization is expired or disconnected. "
                "Run '.venv\\Scripts\\python -m src.tools.login_google_calendar' to re-authenticate."
            )

        # 2. Attempt CalDAV creation if configured
        caldav_mgr = CalDAVManager()
        if caldav_mgr.is_configured():
            caldav_res = caldav_mgr.create_event(
                title=title.strip(),
                start_iso=start_dt.isoformat(),
                end_iso=end_dt.isoformat(),
                description=description.strip(),
                location=location.strip(),
            )
            if caldav_res.get("status") == "success":
                return caldav_res

        # 3. Fallback to local store
        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        new_event = {
            "id": event_id,
            "title": title.strip(),
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "description": description.strip(),
            "location": location.strip(),
            "recurrence": [recurrence] if isinstance(recurrence, str) else list(recurrence) if recurrence else [],
            "created_at": datetime.now().astimezone().isoformat(),
        }

        events_list = load_events()
        events_list.append(new_event)
        save_events(events_list)

        res_payload: dict[str, Any] = {
            "status": "success",
            "event_id": event_id,
            "title": new_event["title"],
            "start": new_event["start"],
            "end": new_event["end"],
            "saved_to": "local_calendar",
            "google_calendar_synced": False,
        }

        if gcal_warning:
            res_payload["google_calendar_status"] = "disconnected"
            res_payload["warning"] = f"Event saved to local calendar store, but was NOT synced to Google Calendar: {gcal_warning}"
            res_payload["message"] = f"Saved '{title}' to local calendar, but could not sync to Google Calendar ({gcal_warning})"
        else:
            res_payload["message"] = f"Successfully scheduled '{title}' on your calendar."

        return res_payload
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create event: {e}",
        }


@mcp.tool()
def create_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Schedule multiple new calendar events in a single batch call.
    Ideal for adding weekly schedules, recurring timetables, or bulk appointments.

    Each item in 'events' should be a dictionary with:
    - title (str): Event name / class name (e.g. 'CISC 457 - 001 Lecture')
    - start_iso (str): Start datetime in ISO format (or relative day/time)
    - end_iso (str): End datetime in ISO format (or relative day/time)
    - location (str, optional): Room / venue
    - description (str, optional): Details
    - recurrence (list[str], optional): e.g. ['RRULE:FREQ=WEEKLY']
    """
    if not events:
        return {"status": "error", "message": "No events provided in batch list."}

    created = []
    errors = []

    for evt in events:
        t = evt.get("title") or evt.get("summary") or evt.get("name") or evt.get("event") or evt.get("task") or "Scheduled Event"
        s_iso = evt.get("start_iso") or evt.get("start") or evt.get("start_time") or evt.get("startTime") or ""
        e_iso = evt.get("end_iso") or evt.get("end") or evt.get("end_time") or evt.get("endTime") or ""
        loc = evt.get("location") or evt.get("loc") or evt.get("room") or ""
        desc = evt.get("description") or evt.get("desc") or evt.get("details") or ""
        rec = evt.get("recurrence")

        res = create_event(
            title=t,
            start_iso=s_iso,
            end_iso=e_iso,
            location=loc,
            description=desc,
            recurrence=rec,
        )
        if res.get("status") == "success":
            created.append({
                "title": t,
                "start": res.get("start") or s_iso,
                "end": res.get("end") or e_iso,
                "location": loc,
                "event_id": res.get("event_id"),
                "html_link": res.get("html_link", ""),
                "google_calendar_synced": res.get("google_calendar_synced", bool(res.get("html_link"))),
                "warning": res.get("warning", ""),
            })
        else:
            errors.append({"title": t, "error": res.get("message")})

    has_unsynced = any(not e.get("google_calendar_synced") for e in created)
    if has_unsynced and any(e.get("warning") for e in created):
        msg = f"Saved {len(created)} events to local calendar, but could not sync to Google Calendar (OAuth authorization expired or disconnected)."
    elif created:
        msg = f"Successfully scheduled {len(created)} events on your calendar."
    else:
        msg = "Failed to schedule events."

    return {
        "status": "success" if created else "error",
        "created_count": len(created),
        "events": created,
        "errors": errors,
        "message": msg,
    }


@mcp.tool()
def sync_local_events_to_google(event_id: str | None = None) -> dict[str, Any]:
    """Push unsynced local events (e.g. created while offline or before OAuth login) to Google Calendar."""
    gcal_manager = GoogleCalendarManager()
    if not gcal_manager.is_logged_in():
        return {
            "status": "error",
            "message": "Google Calendar API is not authenticated. Please run '.venv\\Scripts\\python -m src.tools.login_google_calendar' to log in.",
        }

    events = load_events()
    targets = [
        e for e in events
        if (e.get("id", "").startswith("evt_") or e.get("source") == "local")
        and (event_id is None or e.get("id") == event_id)
    ]
    if not targets:
        return {
            "status": "success",
            "synced_count": 0,
            "message": "No unsynced local events found to push to Google Calendar.",
        }

    synced = []
    errors = []
    synced_local_ids = set()

    for evt in targets:
        res = gcal_manager.create_event(
            title=evt.get("title", "Event"),
            start_iso=evt.get("start", ""),
            end_iso=evt.get("end", ""),
            description=evt.get("description", ""),
            location=evt.get("location", ""),
            recurrence=evt.get("recurrence"),
        )
        if res.get("status") == "success":
            synced.append(res)
            synced_local_ids.add(evt.get("id"))
        else:
            errors.append({"title": evt.get("title"), "error": res.get("message")})

    if synced_local_ids:
        remaining = [e for e in events if e.get("id") not in synced_local_ids]
        save_events(remaining)

    return {
        "status": "success" if synced else "error",
        "synced_count": len(synced),
        "synced_events": synced,
        "errors": errors,
        "message": f"Successfully synced {len(synced)} events to Google Calendar." if synced else "Failed to sync events to Google Calendar.",
    }


@mcp.tool()
def authenticate_google_calendar() -> dict[str, Any]:
    """Launch the Google Calendar OAuth browser authentication flow to connect or refresh account permissions."""
    gcal = GoogleCalendarManager()
    if not gcal.is_oauth_configured():
        return {
            "status": "error",
            "message": "Google OAuth client credentials (credentials.json) not found.",
        }
    if gcal.is_logged_in():
        return {
            "status": "success",
            "message": "Google Calendar is already authenticated and actively connected.",
        }
    try:
        import subprocess
        import sys
        subprocess.Popen([sys.executable, "-m", "src.tools.login_google_calendar"])
        return {
            "status": "success",
            "message": "Launched Google Calendar authentication in your web browser. Please sign in with your Google account to grant calendar access.",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to launch authentication flow: {e}",
        }


@mcp.tool()
def delete_event(event_id: str = "", id: str | None = None) -> dict[str, Any]:
    """Delete an existing calendar event by ID. (Mutating action requiring user confirmation)."""
    event_id = (event_id or id or "").strip()

    # 1. If Google Calendar authenticated and event is a Google event, delete via API
    gcal_manager = GoogleCalendarManager()
    if gcal_manager.is_logged_in() and not event_id.startswith("evt_"):
        live_del = gcal_manager.delete_event(event_id)
        if live_del.get("status") == "success":
            return live_del

    # 2. If CalDAV configured and event has CalDAV prefix, delete via CalDAV
    caldav_mgr = CalDAVManager()
    if caldav_mgr.is_configured() and event_id.startswith("caldav_"):
        caldav_del = caldav_mgr.delete_event(event_id)
        if caldav_del.get("status") == "success":
            return caldav_del

    # 3. Local store deletion
    events = load_events()
    found = None
    remaining = []

    for evt in events:
        if evt.get("id") == event_id:
            found = evt
        else:
            remaining.append(evt)

    if not found:
        if gcal_manager.is_logged_in():
            return gcal_manager.delete_event(event_id)
        return {
            "status": "error",
            "message": f"Event with ID '{event_id}' not found.",
        }

    save_events(remaining)
    res_del: dict[str, Any] = {
        "status": "success",
        "deleted_event": found,
        "message": f"Successfully deleted event '{found.get('title', event_id)}'.",
    }
    if not gcal_manager.is_logged_in() and (gcal_manager.token_path.exists() or gcal_manager.is_oauth_configured()):
        res_del["google_calendar_synced"] = False
        res_del["warning"] = "Deleted from local calendar only. Google Calendar was not updated because Google OAuth is expired or disconnected."
    return res_del


@mcp.tool()
def update_event(
    event_id: str = "",
    title: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    color: str | int | None = None,
    description: str | None = None,
    location: str | None = None,
    id: str | None = None,
    name: str | None = None,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Update or patch an existing calendar event (e.g. change color, title, time, or location).
    Colors supported: 'red'/'tomato' (11), 'blue'/'blueberry' (9), 'green'/'basil' (10),
    'orange'/'tangerine' (6), 'yellow'/'banana' (5), 'purple'/'grape' (3), 'pink'/'flamingo' (4),
    'peacock'/'cyan' (7), 'sage'/'mint' (2), 'lavender' (1), 'graphite'/'gray' (8).
    """
    actual_id = (event_id or id or "").strip()
    actual_title = title or name or summary
    start_iso = start_iso or start
    end_iso = end_iso or end

    # 1. Attempt live Google Calendar update if authenticated
    gcal_manager = GoogleCalendarManager()
    if gcal_manager.is_logged_in() and not actual_id.startswith("evt_"):
        return gcal_manager.update_event(
            event_id=actual_id,
            title=actual_title,
            start_iso=start_iso,
            end_iso=end_iso,
            color=color,
            description=description,
            location=location,
        )

    # 2. Local store fallback
    events = load_events()
    found = None
    for idx, evt in enumerate(events):
        if evt.get("id") == actual_id or (not actual_id and actual_title and actual_title.lower() in evt.get("title", "").lower()):
            found = evt
            if actual_title is not None:
                events[idx]["title"] = actual_title.strip()
            if start_iso is not None:
                events[idx]["start"] = _parse_iso(start_iso).isoformat()
            if end_iso is not None:
                events[idx]["end"] = _parse_iso(end_iso).isoformat()
            if color is not None:
                events[idx]["color"] = str(color)
                events[idx]["color_id"] = str(color)
            if description is not None:
                events[idx]["description"] = description.strip()
            if location is not None:
                events[idx]["location"] = location.strip()
            save_events(events)
            res_upd: dict[str, Any] = {
                "status": "success",
                "event_id": events[idx].get("id", actual_id),
                "title": events[idx]["title"],
                "color": str(color) if color else None,
                "message": f"Successfully updated event '{events[idx]['title']}'.",
            }
            if not gcal_manager.is_logged_in() and (gcal_manager.token_path.exists() or gcal_manager.is_oauth_configured()):
                res_upd["google_calendar_synced"] = False
                res_upd["warning"] = "Updated in local calendar only. Google Calendar was not updated because Google OAuth is expired or disconnected."
            return res_upd

    # If ID was not local, check if Google Calendar knows it
    if gcal_manager.is_logged_in():
        return gcal_manager.update_event(
            event_id=actual_id,
            title=actual_title,
            start_iso=start_iso,
            end_iso=end_iso,
            color=color,
            description=description,
            location=location,
        )

    return {
        "status": "error",
        "message": f"Event with ID '{actual_id}' not found.",
    }


@mcp.tool()
def update_events(
    query: str | None = None,
    color: str | int | None = None,
    event_ids: list[str] | None = None,
    time_window_days: int = 14,
) -> dict[str, Any]:
    """Bulk update or color-code multiple events matching a search query or list of IDs.
    Ideal for color-coding class schedules (e.g. 'color code all class schedule to red'),
    recurring meetings, or batch project events.
    """
    gcal_manager = GoogleCalendarManager()
    if gcal_manager.is_logged_in():
        return gcal_manager.update_events(
            query=query,
            color=color,
            event_ids=event_ids,
            time_window_days=time_window_days,
        )

    # Local store fallback
    events = load_events()
    target_indices = []
    if event_ids:
        ids_set = set(event_ids)
        target_indices = [i for i, e in enumerate(events) if e.get("id") in ids_set]
    elif query:
        q_lower = query.strip().lower()
        target_indices = [
            i for i, e in enumerate(events)
            if q_lower in e.get("title", "").lower() or q_lower in e.get("description", "").lower()
        ]
    else:
        target_indices = list(range(len(events)))

    if not target_indices:
        return {"status": "error", "message": f"No local events matched query '{query or ''}'."}

    updated_titles = []
    for idx in target_indices:
        if color is not None:
            events[idx]["color"] = str(color)
            events[idx]["color_id"] = str(color)
        updated_titles.append(events[idx].get("title", f"Event #{idx}"))

    save_events(events)
    return {
        "status": "success",
        "updated_count": len(updated_titles),
        "color": str(color),
        "updated_events": updated_titles,
        "message": f"Successfully updated {len(updated_titles)} events.",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
