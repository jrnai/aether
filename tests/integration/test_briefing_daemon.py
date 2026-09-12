import json
import pytest
from datetime import datetime
from pathlib import Path

from src.client.ollama_client import OllamaClient
from src.daemon.briefing import BriefingService
from src.storage.db import DatabaseManager


@pytest.fixture(autouse=True)
def seed_briefing_test_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate and seed briefing test fixtures in tmp_path."""
    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AETHER_VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setenv("GOOGLE_CALENDAR_ICAL_URL", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN_PATH", str(tmp_path / "nonexistent_token.json"))
    monkeypatch.setenv("IMAP_SERVER", "")
    monkeypatch.setenv("MS_GRAPH_CLIENT_ID", "")

    now = datetime.now().astimezone()
    today_str = now.strftime("%Y-%m-%d")
    sample_events = [
        {
            "id": "evt_test_briefing_1",
            "title": "Architecture Sync",
            "start": now.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(),
            "end": now.replace(hour=11, minute=0, second=0, microsecond=0).isoformat(),
            "description": "Weekly Project Aether architecture review",
            "location": "Zoom",
        }
    ]
    with open(tmp_path / "calendar_events.json", "w", encoding="utf-8") as f:
        json.dump(sample_events, f)

    sample_emails = [
        {
            "id": "msg_test_briefing_1",
            "account": "personal",
            "account_label": "Personal Gmail",
            "sender": "sarah@example.com",
            "subject": "Q3 Review",
            "date": now.replace(hour=9, minute=0, second=0, microsecond=0).isoformat(),
            "read": False,
            "body": "Let's review the roadmap today.",
        }
    ]
    with open(tmp_path / "mail_inbox.json", "w", encoding="utf-8") as f:
        json.dump(sample_emails, f)


def test_briefing_service_context_gathering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:

    db = DatabaseManager(db_path=tmp_path / "test.db")
    service = BriefingService(db=db)

    context = service.gather_briefing_context()
    assert "date" in context
    assert "weekday" in context
    assert len(context["events"]) >= 1
    assert len(context["unread_emails"]) >= 1

    # Verify SQLite caching
    with db._get_connection() as conn:
        event_count = conn.execute("SELECT COUNT(*) FROM cached_events").fetchone()[0]
        assert event_count >= 1

        email_count = conn.execute("SELECT COUNT(*) FROM cached_emails").fetchone()[0]
        assert email_count >= 1


def test_live_morning_briefing_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = OllamaClient(default_model="qwen2.5:7b-instruct")
    if not client.is_connected():
        pytest.skip("Local Ollama is not reachable.")

    monkeypatch.setenv("AETHER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AETHER_VAULT_DIR", str(tmp_path / "vault"))

    db = DatabaseManager(db_path=tmp_path / "test.db")
    service = BriefingService(client=client, db=db)

    today = datetime.now().astimezone()
    today_str = today.strftime("%Y-%m-%d")

    briefing_text, note_path = service.run_briefing_cycle(target_date=today)
    print("\n--- Generated Morning Briefing ---\n", briefing_text)

    assert len(briefing_text) > 100
    assert note_path.exists()

    content = note_path.read_text(encoding="utf-8")
    assert "## 🌅 Morning Briefing" in content
    assert briefing_text.strip()[:30] in content

    # Verify audit log entry in SQLite
    logs = db.get_audit_logs(limit=5)
    assert any(log["tool_name"] == "generate_morning_briefing" for log in logs)
