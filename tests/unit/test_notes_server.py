"""Unit tests for FastMCP notes server functions and sandbox security."""
import pytest
from pathlib import Path
from src.servers.notes_server import (
    get_vault_dir,
    resolve_safe_path,
    search_notes,
    read_project_notes,
    read_daily_note,
    add_todo_item,
    append_note,
)


@pytest.fixture(autouse=True)
def isolate_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure notes server tests run in an isolated vault fixture."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "daily").mkdir(parents=True, exist_ok=True)
    (vault_dir / "projects").mkdir(parents=True, exist_ok=True)

    (vault_dir / "Inbox.md").write_text(
        "# Inbox\n\nTasks captured on the fly:\n\n- [ ] Review quarterly cloud hosting costs #finance\n",
        encoding="utf-8",
    )
    (vault_dir / "projects" / "Aether.md").write_text(
        "# Project Aether\n\nModular, privacy-first local desktop automation agent.\n- Running Ollama locally with qwen2.5:7b-instruct.\n",
        encoding="utf-8",
    )
    (vault_dir / "daily" / "2026-09-04.md").write_text(
        "# Daily Note: Friday, September 4, 2026\n\n## Priorities\n- [x] Complete specifications\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AETHER_VAULT_DIR", str(vault_dir))


def test_resolve_safe_path_valid() -> None:
    vault_dir = get_vault_dir()
    path = resolve_safe_path("Inbox")
    assert path == (vault_dir / "Inbox.md").resolve()
    assert path.is_relative_to(vault_dir)


def test_resolve_safe_path_traversal_denied() -> None:
    with pytest.raises(PermissionError, match="outside the vault sandbox"):
        resolve_safe_path("../../windows/system32")


def test_read_project_notes_existing() -> None:
    content = read_project_notes("Inbox")
    assert "Tasks captured on the fly:" in content
    assert "Review quarterly cloud hosting costs" in content


def test_read_project_notes_subdirectory() -> None:
    content = read_project_notes("Aether")
    assert "Project Aether" in content


def test_read_project_notes_nonexistent() -> None:
    res = read_project_notes("Nonexistent_Project_1234")
    assert "does not exist in vault" in res


def test_read_daily_note() -> None:
    content = read_daily_note("2026-09-04")
    assert "Daily Note: Friday, September 4, 2026" in content


def test_search_notes_keyword_and_tag() -> None:
    # Test keyword search
    results = search_notes(query="Ollama")
    assert len(results) > 0
    assert any("qwen2.5" in r["snippet"].lower() or "ollama" in r["snippet"].lower() for r in results)

    # Test tag search
    tag_results = search_notes(query="costs", tag="finance")
    assert len(tag_results) > 0
    assert "Inbox.md" in tag_results[0]["file"]


def test_add_todo_item(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Point vault to temporary directory
    monkeypatch.setenv("AETHER_VAULT_DIR", str(tmp_path))

    res = add_todo_item(task="Test task item", project="TestProject", due_date="2026-09-10")
    assert res["status"] == "success"
    assert res["file"] == "TestProject.md"

    # Verify file content
    created_file = tmp_path / "TestProject.md"
    assert created_file.exists()
    content = created_file.read_text(encoding="utf-8")
    assert "- [ ] Test task item due::2026-09-10\n" == content


def test_append_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_VAULT_DIR", str(tmp_path))

    res = append_note(project="MeetingNotes", content="Discussed MCP roadmap.", section="Meeting 1")
    assert res["status"] == "success"

    target_file = tmp_path / "MeetingNotes.md"
    assert target_file.exists()
    content = target_file.read_text(encoding="utf-8")
    assert "## Meeting 1" in content
    assert "Discussed MCP roadmap." in content
