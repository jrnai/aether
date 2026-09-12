"""Unit tests for CalDAVManager client integration and configuration."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from src.servers.caldav_client import CalDAVManager


def test_caldav_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    # Initially not configured
    monkeypatch.delenv("CALENDAR_URL", raising=False)
    monkeypatch.delenv("CALENDAR_USER", raising=False)
    monkeypatch.delenv("CALENDAR_PASSWORD", raising=False)
    monkeypatch.delenv("CALENDAR_PROVIDER", raising=False)

    mgr = CalDAVManager()
    assert mgr.is_configured() is False

    # Configured via env
    monkeypatch.setenv("CALENDAR_URL", "http://localhost:5232/dav")
    monkeypatch.setenv("CALENDAR_USER", "user")
    monkeypatch.setenv("CALENDAR_PASSWORD", "secret")

    mgr2 = CalDAVManager()
    assert mgr2.is_configured() is True


def test_caldav_fetch_events_mocked() -> None:
    mgr = CalDAVManager(url="http://mock-caldav.local", username="u", password="p")
    mock_cal = MagicMock()

    mock_vevent = MagicMock()
    mock_vevent.name = "VEVENT"
    mock_vevent.get.side_effect = lambda k, default=None: {
        "uid": "uid_12345",
        "summary": "CalDAV Test Event",
        "description": "Mocked test event",
        "location": "Room 202",
        "dtstart": MagicMock(dt=datetime(2026, 9, 5, 10, 0)),
        "dtend": MagicMock(dt=datetime(2026, 9, 5, 11, 0)),
    }.get(k, default)

    mock_item = MagicMock()
    mock_item.icalendar_component = mock_vevent
    mock_cal.search.return_value = [mock_item]

    mgr._calendar = mock_cal

    start = datetime(2026, 9, 5, 0, 0)
    end = datetime(2026, 9, 5, 23, 59)

    events = mgr.fetch_events(start, end)
    assert len(events) == 1
    assert events[0]["id"] == "uid_12345"
    assert events[0]["title"] == "CalDAV Test Event"
    assert "2026-09-05" in events[0]["start"]


def test_caldav_create_event_mocked() -> None:
    mgr = CalDAVManager(url="http://mock-caldav.local", username="u", password="p")
    mock_cal = MagicMock()
    mgr._calendar = mock_cal

    res = mgr.create_event(
        title="New Sync",
        start_iso="2026-09-05T14:00:00Z",
        end_iso="2026-09-05T15:00:00Z",
        description="Sync meeting",
    )
    assert res["status"] == "success"
    assert res["title"] == "New Sync"
    assert mock_cal.save_event.called


def test_caldav_delete_event_mocked() -> None:
    mgr = CalDAVManager(url="http://mock-caldav.local", username="u", password="p")
    mock_cal = MagicMock()
    mock_evt = MagicMock()
    mock_cal.event_by_uid.return_value = mock_evt
    mgr._calendar = mock_cal

    res = mgr.delete_event("caldav_test_uid")
    assert res["status"] == "success"
    assert mock_evt.delete.called
