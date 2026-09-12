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


