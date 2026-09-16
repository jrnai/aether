"""Unit tests for FastMCP calendar server operations."""
import json
from datetime import datetime
from pathlib import Path
import pytest
from src.servers.calendar_server import (
    list_events,
    get_free_slots,
    create_event,
    create_events,
    delete_event,
    load_events,
    update_event,
    update_events,
    sync_local_events_to_google,
    _parse_iso,
)


@pytest.fixture(autouse=True)
def isolate_local_calendar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests test local fallback by default without network calls."""
    monkeypatch.setenv("GOOGLE_CALENDAR_ICAL_URL", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_PATH", str(tmp_path / "non_existent_token.json"))
    monkeypatch.setenv("GOOGLE_CALENDAR_CREDENTIALS_PATH", str(tmp_path / "non_existent_creds.json"))


def test_list_events_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    now = datetime.now().astimezone()
    today_str = now.strftime("%Y-%m-%d")
    tz_suffix = now.strftime("%z")
    tz_formatted = f"{tz_suffix[:3]}:{tz_suffix[3:]}" if len(tz_suffix) == 5 else "+00:00"
    sample_events = [
        {
            "id": "evt_test_1",
            "title": "Architecture Sync",
            "start": f"{today_str}T10:00:00{tz_formatted}",
            "end": f"{today_str}T11:00:00{tz_formatted}",
            "description": "Weekly Project Aether architecture review",
            "location": "Zoom",
        },
        {
            "id": "evt_test_2",
            "title": "Team Standup",
            "start": f"{today_str}T14:00:00{tz_formatted}",
            "end": f"{today_str}T14:30:00{tz_formatted}",
            "description": "Sprint check-in",
            "location": "Discord",
        },
    ]
    with open(tmp_path / "calendar_events.json", "w", encoding="utf-8") as f:
        json.dump(sample_events, f)

    events = list_events()
    assert len(events) >= 2
    titles = [e["title"] for e in events]
    assert "Architecture Sync" in titles
    assert "Team Standup" in titles
    assert all(e.get("is_today") is True for e in events)


def test_list_events_single_day_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    from datetime import timedelta
    now = datetime.now().astimezone()
    today_str = now.strftime("%Y-%m-%d")
    monday_dt = now + timedelta(days=2)
    monday_str = monday_dt.strftime("%Y-%m-%d")
    tz_suffix = now.strftime("%z")
    tz_formatted = f"{tz_suffix[:3]}:{tz_suffix[3:]}" if len(tz_suffix) == 5 else "+00:00"

    sample_events = [
        {
            "id": "evt_today_1",
            "title": "Today Standup",
            "start": f"{today_str}T09:00:00{tz_formatted}",
            "end": f"{today_str}T09:30:00{tz_formatted}",
        },
        {
            "id": "evt_monday_1",
            "title": "Monday Lecture",
            "start": f"{monday_str}T10:30:00{tz_formatted}",
            "end": f"{monday_str}T11:30:00{tz_formatted}",
        },
    ]
    with open(tmp_path / "calendar_events.json", "w", encoding="utf-8") as f:
        json.dump(sample_events, f)

    # 1. Default call (no args) must only return today's event, never leaking Monday
    events_default = list_events()
    assert len(events_default) == 1
    assert events_default[0]["title"] == "Today Standup"
    assert events_default[0]["is_today"] is True
    assert events_default[0]["date"] == today_str

    # 2. Querying by explicit date for today must also only return today's event
    events_date = list_events(date=today_str)
    assert len(events_date) == 1
    assert events_date[0]["title"] == "Today Standup"

    # 3. Querying for Monday must only return Monday's event
    events_monday = list_events(date=monday_str)
    assert len(events_monday) == 1
    assert events_monday[0]["title"] == "Monday Lecture"
    assert events_monday[0]["is_today"] is False
    assert events_monday[0]["date"] == monday_str

    # 4. Multi-day range returns both
    events_range = list_events(start_iso=f"{today_str}T00:00:00{tz_formatted}", end_iso=f"{monday_str}T23:59:59{tz_formatted}")
    assert len(events_range) == 2


def test_get_free_slots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    now = datetime.now().astimezone()
    today_str = now.strftime("%Y-%m-%d")
    tz_suffix = now.strftime("%z")
    tz_formatted = f"{tz_suffix[:3]}:{tz_suffix[3:]}" if len(tz_suffix) == 5 else "+00:00"
    sample_events = [
        {
            "id": "evt_test_1",
            "title": "Architecture Sync",
            "start": f"{today_str}T10:00:00{tz_formatted}",
            "end": f"{today_str}T11:00:00{tz_formatted}",
            "description": "Weekly Project Aether architecture review",
            "location": "Zoom",
        },
        {
            "id": "evt_test_2",
            "title": "Team Standup",
            "start": f"{today_str}T14:00:00{tz_formatted}",
            "end": f"{today_str}T14:30:00{tz_formatted}",
            "description": "Sprint check-in",
            "location": "Discord",
        },
    ]
    with open(tmp_path / "calendar_events.json", "w", encoding="utf-8") as f:
        json.dump(sample_events, f)

    # Working hours 09:00 - 18:00
    # Architecture Sync: 10:00 - 11:00 (buffered: 09:30 - 11:30)
    # Team Standup: 14:00 - 14:30 (buffered: 13:30 - 15:00)
    # Default 30-minute buffer ensures no focus session is within 30 mins before or after any event:
    slots = get_free_slots(duration_minutes=30)
    assert len(slots) == 3
    slot_starts = [s["start"] for s in slots]
    slot_ends = [s["end"] for s in slots]
    assert slot_starts == ["09:00", "11:30", "15:00"]
    assert slot_ends == ["09:30", "13:30", "18:00"]

    # Verify unbuffered behavior with buffer_minutes=0
    unbuffered = get_free_slots(duration_minutes=30, buffer_minutes=0)
    unbuffered_starts = [s["start"] for s in unbuffered]
    assert unbuffered_starts == ["09:00", "11:00", "14:30"]


def test_get_free_slots_buffer_edge_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that buffer merges overlapping buffers and captures boundary events."""
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    now = datetime.now().astimezone()
    today_str = now.strftime("%Y-%m-%d")
    tz_suffix = now.strftime("%z")
    tz_formatted = f"{tz_suffix[:3]}:{tz_suffix[3:]}" if len(tz_suffix) == 5 else "+00:00"

    # Event 1: Ends at 09:00 (workday start) -> 30m buffer extends to 09:30
    # Event 2: 11:00 - 12:00 -> buffered: 10:30 - 12:30
    # Event 3: 12:45 - 13:30 -> buffered: 12:15 - 14:00 (overlaps with Event 2 buffer, merges: 10:30 - 14:00)
    sample_events = [
        {
            "id": "evt_morning",
            "title": "Breakfast Briefing",
            "start": f"{today_str}T08:30:00{tz_formatted}",
            "end": f"{today_str}T09:00:00{tz_formatted}",
        },
        {
            "id": "evt_midday_1",
            "title": "Design Review",
            "start": f"{today_str}T11:00:00{tz_formatted}",
            "end": f"{today_str}T12:00:00{tz_formatted}",
        },
        {
            "id": "evt_midday_2",
            "title": "Tech Talk",
            "start": f"{today_str}T12:45:00{tz_formatted}",
            "end": f"{today_str}T13:30:00{tz_formatted}",
        },
    ]
    with open(tmp_path / "calendar_events.json", "w", encoding="utf-8") as f:
        json.dump(sample_events, f)

    slots = get_free_slots(duration_minutes=30)
    slot_starts = [s["start"] for s in slots]
    slot_ends = [s["end"] for s in slots]

    # Morning slot cannot start before 09:30 due to Event 1's 30-min buffer:
    assert slot_starts[0] == "09:30"
    assert slot_ends[0] == "10:30"

    # Between 12:00 and 12:45 (45 mins gap) is within 30 mins of Event 2 or Event 3 -> merged, no slot!
    # Afternoon slot starts at 14:00 (30 mins after Event 3):
    assert slot_starts[1] == "14:00"
    assert slot_ends[1] == "18:00"
    assert len(slots) == 2



def test_create_and_delete_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))

    res = create_event(
        title="1:1 Sync with Alex",
        start_iso="2026-09-10T15:00:00+08:00",
        end_iso="2026-09-10T16:00:00+08:00",
        description="Discuss Q3 goals",
    )

    assert res["status"] == "success"
    event_id = res["event_id"]
    assert event_id.startswith("evt_")

    # Verify event appears in list
    events = list_events(start_iso="2026-09-10T00:00:00+08:00", end_iso="2026-09-10T23:59:59+08:00")
    assert any(e["id"] == event_id for e in events)

    # Delete event
    del_res = delete_event(event_id)
    assert del_res["status"] == "success"

    # Verify event is removed
    events_after = list_events(start_iso="2026-09-10T00:00:00+08:00", end_iso="2026-09-10T23:59:59+08:00")
    assert not any(e["id"] == event_id for e in events_after)


def test_create_event_invalid_times() -> None:
    # End before start
    res = create_event(
        title="Time Travel",
        start_iso="2026-09-10T16:00:00+08:00",
        end_iso="2026-09-10T15:00:00+08:00",
    )
    assert res["status"] == "error"
    assert "strictly after start time" in res["message"]


def test_calendar_server_delegates_to_google_calendar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    from unittest.mock import MagicMock, patch

    with patch("src.servers.calendar_server.GoogleCalendarManager") as mock_mgr_cls:
        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr
        mock_mgr.is_logged_in.return_value = True

        mock_mgr.fetch_events.return_value = [
            {
                "id": "gcal_live_1",
                "title": "Live Google Meet",
                "start": "2026-09-07T10:00:00+08:00",
                "end": "2026-09-07T11:00:00+08:00",
            }
        ]
        mock_mgr.create_event.return_value = {
            "status": "success",
            "event_id": "gcal_live_2",
            "title": "New Event",
            "start": "2026-09-07T14:00:00+08:00",
            "end": "2026-09-07T15:00:00+08:00",
            "html_link": "https://calendar.google.com",
        }

        # Test list_events delegates
        evts = list_events(start_iso="2026-09-07T00:00:00+08:00", end_iso="2026-09-07T23:59:59+08:00")
        assert len(evts) == 1
        assert evts[0]["title"] == "Live Google Meet"

        # Test create_event delegates
        c_res = create_event(
            title="New Event",
            start_iso="2026-09-07T14:00:00+08:00",
            end_iso="2026-09-07T15:00:00+08:00",
        )
        assert c_res["status"] == "success"
        assert c_res["event_id"] == "gcal_live_2"
        mock_mgr.create_event.assert_called_once()


def test_create_events_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    events_to_schedule = [
        {
            "title": "CISC 457 Lecture",
            "start_iso": "2026-09-07T10:30:00-04:00",
            "end_iso": "2026-09-07T11:30:00-04:00",
            "location": "Stirling Hall A",
        },
        {
            "title": "STAT 361 Lecture",
            "start_iso": "2026-09-07T14:30:00-04:00",
            "end_iso": "2026-09-07T15:30:00-04:00",
            "location": "Jeffery Hall 128",
        },
    ]

    res = create_events(events_to_schedule)
    assert res["status"] == "success"
    assert res["created_count"] == 2
    assert len(res["events"]) == 2

    # Also test delegation via create_event(events=[...])
    delegated_res = create_event(events=[
        {
            "title": "CISC 251 Lecture",
            "start_iso": "2026-09-08T08:30:00-04:00",
            "end_iso": "2026-09-08T09:30:00-04:00",
            "location": "Stirling Hall B",
        }
    ])
    assert delegated_res["status"] == "success"
    assert delegated_res["created_count"] == 1


def test_relative_weekday_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    res = create_event(
        title="Relative Monday Class",
        start_iso="Monday 10:30 AM",
        end_iso="Monday 11:30 AM",
        location="Stirling Hall A",
    )
    assert res["status"] == "success"
    assert "10:30" in res["start"]
    assert "11:30" in res["end"]


def test_update_event_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    c_res = create_event(
        title="Original Title",
        start_iso="2026-09-12T10:00:00-04:00",
        end_iso="2026-09-12T11:00:00-04:00",
    )
    assert c_res["status"] == "success"
    event_id = c_res["event_id"]

    u_res = update_event(
        event_id=event_id,
        title="Updated Title",
        color="red",
        location="Room 101",
    )
    assert u_res["status"] == "success"
    assert u_res["title"] == "Updated Title"

    events = load_events()
    updated_evt = [e for e in events if e.get("id") == event_id][0]
    assert updated_evt["title"] == "Updated Title"
    assert updated_evt["location"] == "Room 101"
    assert updated_evt["color"] == "red"


def test_update_events_bulk_color(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    create_events([
        {"title": "CISC 457 Lecture", "start_iso": "2026-09-14T10:00:00-04:00", "end_iso": "2026-09-14T11:00:00-04:00"},
        {"title": "CISC 251 Lecture", "start_iso": "2026-09-14T11:00:00-04:00", "end_iso": "2026-09-14T12:00:00-04:00"},
        {"title": "Doctor Appointment", "start_iso": "2026-09-14T14:00:00-04:00", "end_iso": "2026-09-14T15:00:00-04:00"},
    ])

    # Bulk update only lecture events to red
    res = update_events(query="Lecture", color="red")
    assert res["status"] == "success"
    assert res["updated_count"] == 2
    assert "CISC 457 Lecture" in res["updated_events"]
    assert "CISC 251 Lecture" in res["updated_events"]

    events = load_events()
    lecture_evts = [e for e in events if "Lecture" in e.get("title", "")]
    assert all(e.get("color") == "red" for e in lecture_evts)

    doc_evt = [e for e in events if "Doctor" in e.get("title", "")][0]
    assert "color" not in doc_evt or doc_evt.get("color") != "red"


def test_relative_date_parsing_today_tonight_tomorrow() -> None:
    from src.servers.calendar_server import _parse_iso
    from datetime import timedelta
    now = datetime.now().astimezone()
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    dt1 = _parse_iso("11 PM today")
    assert dt1.strftime("%Y-%m-%d") == today_str
    assert dt1.hour == 23 and dt1.minute == 0

    dt2 = _parse_iso("today at 11pm")
    assert dt2.strftime("%Y-%m-%d") == today_str
    assert dt2.hour == 23 and dt2.minute == 0

    dt3 = _parse_iso("tonight 11pm")
    assert dt3.strftime("%Y-%m-%d") == today_str
    assert dt3.hour == 23 and dt3.minute == 0

    dt4 = _parse_iso("tomorrow at 10:30am")
    assert dt4.strftime("%Y-%m-%d") == tomorrow_str
    assert dt4.hour == 10 and dt4.minute == 30

    dt5 = _parse_iso("11pm")
    assert dt5.strftime("%Y-%m-%d") == today_str
    assert dt5.hour == 23 and dt5.minute == 0


def test_create_event_omitted_end_time_defaults_to_30_min(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    res = create_event(
        title="Take out the trash",
        start="11 PM today",
    )
    assert res["status"] == "success"
    assert "23:00:00" in res["start"]
    assert "23:30:00" in res["end"]


def test_create_event_flexible_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    res = create_event(
        summary="Doctor Checkup",
        start_time="2026-09-15T14:00:00-04:00",
        end_time="2026-09-15T15:00:00-04:00",
    )
    assert res["status"] == "success"
    assert res["title"] == "Doctor Checkup"
    assert "14:00:00" in res["start"]
    assert "15:00:00" in res["end"]


def test_create_event_dot_separated_and_duration_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    res = create_event(
        task="Take out the trash",
        start="11.30 pm today",
        duration_minutes=30,
    )
    assert res["status"] == "success"
    assert res["title"] == "Take out the trash"
    assert "23:30:00" in res["start"]
    assert "00:00:00" in res["end"]


def test_parse_iso_dot_separated_times() -> None:
    now = datetime.now().astimezone()
    today_str = now.strftime("%Y-%m-%d")

    dt1 = _parse_iso("11.30 pm today")
    assert dt1.strftime("%Y-%m-%d") == today_str
    assert dt1.hour == 23 and dt1.minute == 30

    dt2 = _parse_iso("11.30am")
    assert dt2.strftime("%Y-%m-%d") == today_str
    assert dt2.hour == 11 and dt2.minute == 30

    dt3 = _parse_iso("8.15 pm")
    assert dt3.strftime("%Y-%m-%d") == today_str
    assert dt3.hour == 20 and dt3.minute == 15


def test_create_event_warns_when_oauth_disconnected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    from unittest.mock import MagicMock, patch

    with patch("src.servers.calendar_server.GoogleCalendarManager") as mock_mgr_cls:
        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr
        mock_mgr.is_logged_in.return_value = False
        mock_mgr.token_path.exists.return_value = True
        mock_mgr.is_oauth_configured.return_value = True

        res = create_event(
            title="Dendy's appointment",
            start_iso="2026-09-13T08:00:00-04:00",
            end_iso="2026-09-13T08:30:00-04:00",
        )

        assert res["status"] == "success"
        assert res["saved_to"] == "local_calendar"
        assert res["google_calendar_synced"] is False
        assert res["google_calendar_status"] == "disconnected"
        assert "warning" in res
        assert "OAuth authorization is expired or disconnected" in res["warning"]
        assert "could not sync to Google Calendar" in res["message"]


def test_sync_local_events_to_google(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    from unittest.mock import MagicMock, patch

    sample_events = [
        {
            "id": "evt_local_123",
            "title": "Pending Doctor Appointment",
            "start": "2026-09-13T08:00:00-04:00",
            "end": "2026-09-13T08:30:00-04:00",
            "description": "Routine checkup",
            "location": "Clinic",
        }
    ]
    with open(tmp_path / "calendar_events.json", "w", encoding="utf-8") as f:
        json.dump(sample_events, f)

    with patch("src.servers.calendar_server.GoogleCalendarManager") as mock_mgr_cls:
        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr
        mock_mgr.is_logged_in.return_value = True
        mock_mgr.create_event.return_value = {
            "status": "success",
            "event_id": "gcal_new_999",
            "title": "Pending Doctor Appointment",
            "start": "2026-09-13T08:00:00-04:00",
            "end": "2026-09-13T08:30:00-04:00",
        }

        sync_res = sync_local_events_to_google()

        assert sync_res["status"] == "success"
        assert sync_res["synced_count"] == 1
        mock_mgr.create_event.assert_called_once()
        # Verify local store was updated (evt_local_123 pruned from local store)
        with open(tmp_path / "calendar_events.json", encoding="utf-8") as f:
            updated = json.load(f)
        assert not any(e["id"] == "evt_local_123" for e in updated)


def test_authenticate_google_calendar_tool() -> None:
    from src.servers.calendar_server import authenticate_google_calendar
    from unittest.mock import MagicMock, patch

    with patch("src.servers.calendar_server.GoogleCalendarManager") as mock_mgr_cls, patch("subprocess.Popen") as mock_popen:
        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr
        mock_mgr.is_oauth_configured.return_value = True
        mock_mgr.is_logged_in.return_value = False

        res = authenticate_google_calendar()
        assert res["status"] == "success"
        assert "Launched Google Calendar authentication" in res["message"]
        mock_popen.assert_called_once()




