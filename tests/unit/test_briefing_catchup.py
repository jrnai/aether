"""Unit tests for Once-A-Day Briefing, Missed Days Detection, and Startup Integration."""
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.daemon.briefing import BriefingService
from src.storage.db import DatabaseManager


@pytest.fixture
def temp_db(tmp_path: Path) -> DatabaseManager:
    """Create an isolated test SQLite database."""
    db_file = tmp_path / "test_aether.db"
    return DatabaseManager(db_path=db_file)


@pytest.fixture
def mock_ollama_client() -> MagicMock:
    """Mock OllamaClient to avoid local daemon dependencies in unit tests."""
    mock = MagicMock()
    mock.chat.return_value = {
        "content": "### 🌅 Morning Briefing\n- Great morning! You are all caught up.",
    }
    return mock


def test_system_state_crud(temp_db: DatabaseManager) -> None:
    """Verify get_state and set_state methods in DatabaseManager."""
    assert temp_db.get_state("non_existent") is None
    assert temp_db.get_state("non_existent", default="fallback") == "fallback"

    temp_db.set_state("last_briefing_date", "2026-09-01")
    assert temp_db.get_state("last_briefing_date") == "2026-09-01"

    # Upsert test
    temp_db.set_state("last_briefing_date", "2026-09-02")
    assert temp_db.get_state("last_briefing_date") == "2026-09-02"


def test_detect_missed_days_no_previous(temp_db: DatabaseManager, mock_ollama_client: MagicMock, tmp_path: Path) -> None:
    """Verify that a fresh install with no past date records returns 0 missed days."""
    service = BriefingService(client=mock_ollama_client, db=temp_db)
    now = datetime(2026, 9, 5, 8, 0).astimezone()

    with patch("src.daemon.briefing.get_vault_dir", return_value=tmp_path / "vault"):
        missed = service.detect_missed_days(target_date=now)
        assert missed == []


def test_detect_missed_days_consecutive(temp_db: DatabaseManager, mock_ollama_client: MagicMock) -> None:
    """Verify that running on consecutive days (e.g. yesterday -> today) detects 0 missed days."""
    temp_db.set_state("last_briefing_date", "2026-09-04")
    service = BriefingService(client=mock_ollama_client, db=temp_db)
    now = datetime(2026, 9, 5, 8, 0).astimezone()

    missed = service.detect_missed_days(target_date=now)
    assert missed == []


def test_detect_missed_days_same_day(temp_db: DatabaseManager, mock_ollama_client: MagicMock) -> None:
    """Verify that running twice on the same day detects 0 missed days."""
    temp_db.set_state("last_briefing_date", "2026-09-05")
    service = BriefingService(client=mock_ollama_client, db=temp_db)
    now = datetime(2026, 9, 5, 14, 0).astimezone()

    missed = service.detect_missed_days(target_date=now)
    assert missed == []


def test_detect_missed_days_two_days_gap(temp_db: DatabaseManager, mock_ollama_client: MagicMock) -> None:
    """Verify that a 2-day gap (last run Sept 3, today Sept 5) detects 1 missed day (Sept 4)."""
    temp_db.set_state("last_briefing_date", "2026-09-03")
    service = BriefingService(client=mock_ollama_client, db=temp_db)
    now = datetime(2026, 9, 5, 8, 0).astimezone()

    missed = service.detect_missed_days(target_date=now)
    assert missed == ["2026-09-04"]


def test_detect_missed_days_weekend_gap(temp_db: DatabaseManager, mock_ollama_client: MagicMock) -> None:
    """Verify a multi-day weekend gap (last run Friday Sept 4, today Monday Sept 7)."""
    temp_db.set_state("last_briefing_date", "2026-09-04")
    service = BriefingService(client=mock_ollama_client, db=temp_db)
    now = datetime(2026, 9, 7, 9, 0).astimezone()

    missed = service.detect_missed_days(target_date=now)
    assert missed == ["2026-09-05", "2026-09-06"]


def test_is_briefing_completed_for_today(temp_db: DatabaseManager, mock_ollama_client: MagicMock, tmp_path: Path) -> None:
    """Verify once-per-day completion check."""
    service = BriefingService(client=mock_ollama_client, db=temp_db)
    today_str = "2026-09-05"

    with patch("src.daemon.briefing.get_vault_dir", return_value=tmp_path / "vault"):
        assert not service.is_briefing_completed_for_today(today_str)

        temp_db.set_state("last_briefing_date", today_str)
        assert service.is_briefing_completed_for_today(today_str)


def test_gather_catchup_context(temp_db: DatabaseManager, mock_ollama_client: MagicMock) -> None:
    """Verify catch-up context gathers events and emails for the missed window."""
    service = BriefingService(client=mock_ollama_client, db=temp_db)
    missed_dates = ["2026-09-03", "2026-09-04"]

    with patch("src.daemon.briefing.list_events") as mock_list_events, \
         patch("src.daemon.briefing.fetch_unread_emails") as mock_fetch_emails:
        mock_list_events.return_value = [{"title": "Missed Meeting", "start": "2026-09-03T10:00:00"}]
        mock_fetch_emails.return_value = [{"subject": "Urgent Request", "sender": "prof@ntu.edu.sg"}]

        context = service.gather_catchup_context(missed_dates)
        assert context["missed_dates"] == missed_dates
        assert context["start_date"] == "2026-09-03"
        assert context["end_date"] == "2026-09-04"
        assert len(context["events"]) == 1
        assert len(context["emails"]) == 1


def test_run_briefing_cycle_updates_state(temp_db: DatabaseManager, mock_ollama_client: MagicMock, tmp_path: Path) -> None:
    """Verify run_briefing_cycle writes the date to system_state."""
    service = BriefingService(client=mock_ollama_client, db=temp_db)
    target_dt = datetime(2026, 9, 5, 8, 30).astimezone()

    with patch("src.daemon.briefing.get_vault_dir", return_value=tmp_path / "vault"):
        service.run_briefing_cycle(target_date=target_dt)

    assert temp_db.get_state("last_briefing_date") == "2026-09-05"
    assert temp_db.get_state("last_briefing_timestamp") is not None


def test_run_briefing_cycle_does_not_pollute_inbox_by_default(temp_db: DatabaseManager, mock_ollama_client: MagicMock, tmp_path: Path) -> None:
    """Verify run_briefing_cycle does NOT write action items to Inbox.md by default."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    inbox = vault / "Inbox.md"
    inbox.write_text("# Inbox\n\nTasks captured on the fly:\n", encoding="utf-8")

    mock_ollama_client.chat.return_value = {
        "content": "### 🌅 Morning Briefing\n\n### 🎯 Priority Action Items\n1. Junk task from email",
    }

    service = BriefingService(client=mock_ollama_client, db=temp_db)
    target_dt = datetime(2026, 9, 5, 8, 30).astimezone()

    with patch("src.daemon.briefing.get_vault_dir", return_value=vault):
        service.run_briefing_cycle(target_date=target_dt)

    content = inbox.read_text(encoding="utf-8")
    assert "Junk task from email" not in content
    assert "#briefing" not in content


def test_write_briefing_to_daily_note_appends_date_to_review_task(tmp_path: Path, mock_ollama_client: MagicMock, temp_db: DatabaseManager) -> None:
    """Verify write_briefing_to_daily_note includes the date behind Review Morning Briefing task."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)

    service = BriefingService(client=mock_ollama_client, db=temp_db)
    with patch("src.daemon.briefing.get_vault_dir", return_value=vault):
        note_path = service.write_briefing_to_daily_note("2026-09-09", "Test Morning Briefing text")

    assert note_path.exists()
    content = note_path.read_text(encoding="utf-8")
    assert "- [ ] Review Morning Briefing (2026-09-09)" in content


def test_ensure_web_app_running_already_active() -> None:
    """Verify that ensure_web_app_running focuses window if server is already active."""
    from src.daemon.main import ensure_web_app_running

    with patch("src.web.server._is_aether_running", return_value=True), \
         patch("src.web.server.open_desktop_app_window") as mock_open_win:
        success = ensure_web_app_running(host="127.0.0.1", port=8000, open_browser=True)
        assert success is True
        mock_open_win.assert_called_once_with("http://127.0.0.1:8000", app_mode=True)


def test_ensure_web_app_running_offline_spawns() -> None:
    """Verify that ensure_web_app_running spawns background portal process when offline."""
    from src.daemon.main import ensure_web_app_running

    # Return False initially, then True after spawned
    check_results = [False, True]

    def mock_is_running(h, p):
        if check_results:
            return check_results.pop(0)
        return True

    with patch("src.web.server._is_aether_running", side_effect=mock_is_running), \
         patch("subprocess.Popen") as mock_popen, \
         patch("time.sleep"):
        success = ensure_web_app_running(host="127.0.0.1", port=8000, open_browser=True)
        assert success is True
        assert mock_popen.called
        cmd = mock_popen.call_args[0][0]
        assert "main.py" in cmd
        assert "--portal" in cmd
        assert "--open" in cmd


def test_daemon_main_on_startup_launches_web() -> None:
    """Verify that running daemon with --on-startup automatically triggers ensure_web_app_running."""
    from src.daemon.main import main

    with patch("sys.argv", ["main.py", "--on-startup"]), \
         patch("src.daemon.briefing.BriefingService.is_briefing_completed_for_today", return_value=False), \
         patch("src.daemon.briefing.BriefingService.detect_missed_days", return_value=[]), \
         patch("src.daemon.briefing.BriefingService.run_briefing_cycle", return_value=("Test briefing", Path("/tmp/test.md"))), \
         patch("src.daemon.main.ensure_web_app_running") as mock_ensure_web, \
         patch("time.sleep"):
        main()
        mock_ensure_web.assert_called_once_with(open_browser=True)


def test_daemon_main_on_startup_no_web_flag() -> None:
    """Verify that passing --no-web suppresses the automatic web launch."""
    from src.daemon.main import main

    with patch("sys.argv", ["main.py", "--on-startup", "--no-web"]), \
         patch("src.daemon.briefing.BriefingService.is_briefing_completed_for_today", return_value=False), \
         patch("src.daemon.briefing.BriefingService.detect_missed_days", return_value=[]), \
         patch("src.daemon.briefing.BriefingService.run_briefing_cycle", return_value=("Test briefing", Path("/tmp/test.md"))), \
         patch("src.daemon.main.ensure_web_app_running") as mock_ensure_web, \
         patch("rich.console.Console.input", return_value=""):
        main()
        mock_ensure_web.assert_not_called()


def test_briefing_context_includes_news_headlines(temp_db: DatabaseManager, mock_ollama_client: MagicMock) -> None:
    """Verify gather_briefing_context populates news_headlines from news_service."""
    service = BriefingService(client=mock_ollama_client, db=temp_db)
    sample_news = [{"id": "hn_1", "title": "Big Tech AI Breakthrough", "source": "Hacker News", "score": 200}]

    with patch("src.servers.news_service.get_news", return_value=sample_news):
        context = service.gather_briefing_context()
        assert "news_headlines" in context
        assert len(context["news_headlines"]) == 1
        assert context["news_headlines"][0]["title"] == "Big Tech AI Breakthrough"


def test_briefing_prompt_includes_tech_digest_section(temp_db: DatabaseManager, mock_ollama_client: MagicMock) -> None:
    """Verify generate_briefing_text instructs the model to create 'What Happened in Tech Today'."""
    service = BriefingService(client=mock_ollama_client, db=temp_db)
    context = {
        "date": "2026-09-10",
        "weekday": "Thursday",
        "events": [],
        "free_slots": [],
        "unread_emails": [],
        "inbox_tasks": "",
        "catchup": None,
        "news_headlines": [
            {"title": "Open Source Coder 7B Released", "source": "Hacker News", "score": 450}
        ],
    }

    service.generate_briefing_text(context)
    assert mock_ollama_client.chat.called
    call_args = mock_ollama_client.chat.call_args[1]
    messages = call_args["messages"]
    user_prompt = messages[1]["content"]

    assert "Top Tech Headlines Today:" in user_prompt
    assert "Open Source Coder 7B Released" in user_prompt
    assert "What Happened in Tech Today" in user_prompt


