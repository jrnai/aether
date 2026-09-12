"""Unit tests for GoogleCalendarManager (OAuth 2.0 and iCal feed)."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from src.servers.google_calendar_client import GoogleCalendarManager


def test_manager_credentials_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    creds_file = tmp_path / "credentials.json"
    monkeypatch.setenv("GOOGLE_CALENDAR_CREDENTIALS_PATH", str(creds_file))
    token_file = tmp_path / "calendar_token.json"
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_PATH", str(token_file))

    manager = GoogleCalendarManager()
    assert manager.is_oauth_configured() is False
    assert manager.is_logged_in() is False

    # Create dummy credentials file
    creds_file.write_text(json.dumps({"installed": {"client_id": "dummy"}}), encoding="utf-8")
    assert manager.is_oauth_configured() is True


def test_manager_mocked_api_fetch_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    manager = GoogleCalendarManager()

    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_service.events.return_value = mock_events

    now_iso = datetime.now().astimezone().isoformat()
    mock_events.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "gcal_evt_101",
                "summary": "Project Sync",
                "start": {"dateTime": now_iso},
                "end": {"dateTime": now_iso},
                "description": "Weekly sync",
                "location": "Meet",
                "htmlLink": "https://calendar.google.com/event?id=101",
            }
        ]
    }

    with patch.object(manager, "get_service", return_value=mock_service):
        events = manager.fetch_events_api(datetime.now(), datetime.now() + timedelta(days=1))
        assert len(events) == 1
        assert events[0]["id"] == "gcal_evt_101"
        assert events[0]["title"] == "Project Sync"
        assert events[0]["location"] == "Meet"
        assert events[0]["html_link"] == "https://calendar.google.com/event?id=101"


def test_manager_mocked_create_and_delete_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    manager = GoogleCalendarManager()

    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_service.events.return_value = mock_events

    mock_events.insert.return_value.execute.return_value = {
        "id": "created_evt_99",
        "htmlLink": "https://calendar.google.com/event?id=99",
    }
    mock_events.delete.return_value.execute.return_value = {}

    with patch.object(manager, "is_logged_in", return_value=True):
        with patch.object(manager, "get_service", return_value=mock_service):
            # Create
            res = manager.create_event(
                title="Interview",
                start_iso="2026-09-06T14:00:00+08:00",
                end_iso="2026-09-06T15:00:00+08:00",
                description="Technical chat",
                location="Office Room 2",
            )
            assert res["status"] == "success"
            assert res["event_id"] == "created_evt_99"

            # Delete
            del_res = manager.delete_event("created_evt_99")
            assert del_res["status"] == "success"
            assert del_res["event_id"] == "created_evt_99"


def test_manager_mocked_ical_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GOOGLE_CALENDAR_ICAL_URL", "https://calendar.google.com/calendar/ical/test/basic.ics")

    manager = GoogleCalendarManager()

    ics_content = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Google Inc//Google Calendar//EN
BEGIN:VEVENT
UID:uid_ical_event_123@google.com
SUMMARY:Team Lunch
DTSTART:20260906T040000Z
DTEND:20260906T050000Z
LOCATION:Bistro
DESCRIPTION:Monthly team lunch
END:VEVENT
END:VCALENDAR"""

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = ics_content

    with patch("requests.get", return_value=mock_resp):
        start = datetime(2026, 9, 6, 0, 0).astimezone()
        end = datetime(2026, 9, 7, 0, 0).astimezone()
        events = manager.fetch_events_ical(start, end)

        assert len(events) == 1
        assert events[0]["title"] == "Team Lunch"
        assert events[0]["location"] == "Bistro"
        assert "uid_ical_event_123" in events[0]["id"]


def test_manager_mocked_update_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    manager = GoogleCalendarManager()

    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_service.events.return_value = mock_events

    mock_events.patch.return_value.execute.return_value = {
        "id": "patch_evt_101",
        "summary": "Updated Sync",
        "colorId": "11",
        "htmlLink": "https://calendar.google.com/event?id=101",
        "start": {"dateTime": "2026-09-15T10:00:00-04:00"},
        "end": {"dateTime": "2026-09-15T11:00:00-04:00"},
    }

    with patch.object(manager, "is_logged_in", return_value=True):
        with patch.object(manager, "get_service", return_value=mock_service):
            res = manager.update_event(
                event_id="patch_evt_101",
                title="Updated Sync",
                color="red",
            )
            assert res["status"] == "success"
            assert res["event_id"] == "patch_evt_101"
            assert res["color_id"] == "11"
            assert res["color_name"] == "Tomato"

            mock_events.patch.assert_called_once_with(
                calendarId="primary",
                eventId="patch_evt_101",
                body={"summary": "Updated Sync", "colorId": "11"},
            )


def test_manager_mocked_update_events_bulk_color(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    manager = GoogleCalendarManager()

    mock_service = MagicMock()
    mock_events = MagicMock()
    mock_service.events.return_value = mock_events

    # Mock fetch_events
    dummy_events = [
        {"id": "evt_1", "title": "CISC 457 - 001 Lecture", "start": "2026-09-14T10:00:00-04:00", "end": "2026-09-14T11:00:00-04:00"},
        {"id": "evt_2", "title": "CISC 251 - 001 Lecture", "start": "2026-09-14T11:00:00-04:00", "end": "2026-09-14T12:00:00-04:00"},
        {"id": "evt_3", "title": "Doctor Checkup", "start": "2026-09-14T14:00:00-04:00", "end": "2026-09-14T15:00:00-04:00"},
    ]

    mock_events.patch.return_value.execute.return_value = {
        "colorId": "11",
        "start": {},
        "end": {},
    }

    with patch.object(manager, "is_logged_in", return_value=True):
        with patch.object(manager, "fetch_events", return_value=dummy_events):
            with patch.object(manager, "get_service", return_value=mock_service):
                res = manager.update_events(query="Lecture", color="red")
                assert res["status"] == "success"
                assert res["updated_count"] == 2
                assert "Tomato" in res["color"]
                assert mock_events.patch.call_count == 2

