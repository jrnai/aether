"""Unit tests for SQLite storage manager, session persistence, and audit logging."""
import pytest
from pathlib import Path
from src.storage.db import DatabaseManager


def test_db_initialization_and_wal_mode(tmp_path: Path) -> None:
    db_file = tmp_path / "test_aether.db"
    db = DatabaseManager(db_path=db_file)
    assert db_file.exists()

    with db._get_connection() as conn:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert mode.lower() == "wal"


def test_session_and_messages(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "test.db")
    session_id = db.create_session(title="Unit Test Session")
    assert session_id.startswith("sess_")

    # Add messages
    m1 = db.add_message(session_id=session_id, role="user", content="Hello Aether")
    assert m1 > 0
    m2 = db.add_message(session_id=session_id, role="assistant", content="Hello! How can I help?")
    assert m2 > m1

    # Retrieve messages
    history = db.get_messages(session_id=session_id)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hello Aether"
    assert history[1]["role"] == "assistant"


def test_audit_logging(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "test.db")

    log_id = db.log_audit(
        tool_name="create_event",
        arguments={"title": "Team Sync", "start_iso": "2026-09-05T10:00:00Z"},
        is_mutating=True,
        requires_approval=True,
        user_approved=True,
        execution_status="SUCCESS",
        duration_ms=45,
        result_preview="Event created with ID evt_123",
    )
    assert log_id > 0

    logs = db.get_audit_logs(limit=10)
    assert len(logs) == 1
    record = logs[0]
    assert record["tool_name"] == "create_event"
    assert record["is_mutating"] == 1
    assert record["requires_approval"] == 1
    assert record["user_approved"] == 1
    assert record["execution_status"] == "SUCCESS"
    assert "Team Sync" in record["arguments_json"]


def test_cache_event_and_email(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "test.db")

    # Cache event
    db.cache_event(
        event_id="evt_sample",
        title="Sample Meeting",
        start_time="2026-09-05T14:00:00Z",
        end_time="2026-09-05T15:00:00Z",
        location="Room 101",
    )

    # Cache email
    db.cache_email(
        email_id="msg_sample",
        sender="alice@example.com",
        subject="Hello",
        date_received="2026-09-05T12:00:00Z",
        snippet="Testing cache",
    )

    with db._get_connection() as conn:
        evt = conn.execute("SELECT * FROM cached_events WHERE id = 'evt_sample'").fetchone()
        assert evt is not None
        assert evt["title"] == "Sample Meeting"

        email = conn.execute("SELECT * FROM cached_emails WHERE id = 'msg_sample'").fetchone()
        assert email is not None
        assert email["sender"] == "alice@example.com"


def test_notes_fts_indexing_and_search(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "test.db")
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()

    note1 = vault_dir / "Architecture.md"
    note1.write_text(
        "# Architecture Overview\n\nProject Aether uses SQLite and MCP.\n\n## Security Guidelines\n\nAlways enforce human approval.",
        encoding="utf-8",
    )

    note2 = vault_dir / "Inbox.md"
    note2.write_text(
        "# Inbox\n\n- [ ] Review quarterly budget costs #finance\n- [ ] Update server keys",
        encoding="utf-8",
    )

    indexed = db.index_vault(vault_dir)
    assert indexed > 0

    # Search for "architecture"
    res1 = db.search_notes_fts("architecture")
    assert len(res1) > 0
    assert "Architecture.md" in res1[0]["file"]

    # Search for "finance"
    res2 = db.search_notes_fts("finance")
    assert len(res2) > 0
    assert "Inbox.md" in res2[0]["file"]

