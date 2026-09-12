from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from src.daemon.briefing import extract_action_items
from src.servers.notes_server import (
    add_todo_item,
    complete_todo,
    delete_todo,
    list_todos,
    prune_old_completed_tasks,
    update_todo_priority,
)


@pytest.fixture(autouse=True)
def isolate_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate vault directory to tmp_path for all task tests."""
    monkeypatch.setenv("AETHER_VAULT_DIR", str(tmp_path / "vault"))


def test_add_and_list_todos() -> None:
    """Verify adding tasks and listing them by status."""
    # Add pending task with due date
    res1 = add_todo_item(task="Finish SC3021 assignment", project="Inbox", due_date="2026-09-10")
    assert res1["status"] == "success"

    # Add second task with priority tag
    res2 = add_todo_item(task="Submit expense claims #finance", project="Inbox")
    assert res2["status"] == "success"

    # List pending tasks
    pending = list_todos(project="Inbox", status="pending")
    assert len(pending) == 2
    assert any("SC3021" in t["text"] for t in pending)
    assert any(t["due"] == "2026-09-10" for t in pending)
    assert any("finance" in t["tags"] for t in pending)


def test_complete_todo() -> None:
    """Verify marking a task as completed toggles [ ] to [x]."""
    add_todo_item(task="Buy groceries for the week", project="Inbox")
    add_todo_item(task="Email professor regarding thesis", project="Inbox")

    # Complete the first task
    comp_res = complete_todo(task_query="groceries", project="Inbox")
    assert comp_res["status"] == "success"
    assert "- [x]" in comp_res["task"]

    # Verify only 1 pending remains
    pending = list_todos(project="Inbox", status="pending")
    assert len(pending) == 1
    assert "thesis" in pending[0]["text"]

    # Verify completed task is listed in completed
    completed = list_todos(project="Inbox", status="completed")
    assert len(completed) == 1
    assert "groceries" in completed[0]["text"]


def test_delete_todo() -> None:
    """Verify deleting a task removes it completely from the file."""
    add_todo_item(task="Task to be deleted", project="Inbox")
    add_todo_item(task="Task to keep", project="Inbox")

    del_res = delete_todo(task_query="deleted", project="Inbox")
    assert del_res["status"] == "success"

    remaining = list_todos(project="Inbox", status="all")
    assert len(remaining) == 1
    assert remaining[0]["text"] == "Task to keep"


def test_extract_action_items() -> None:
    """Verify extracting action items from morning briefing markdown."""
    briefing = """
### 📅 Today's Schedule
- 10:00 Meeting

### 🎯 Priority Action Items
1. Review pull request for authentication module
2. Prepare slides for presentation
3. Follow up with client regarding invoices

### ⏳ Free Focus Windows
- 14:00 - 16:00
"""
    items = extract_action_items(briefing)
    assert len(items) == 3
    assert "Review pull request" in items[0]
    assert "Prepare slides" in items[1]
    assert "Follow up with client" in items[2]


def test_complete_todo_attaches_timestamp() -> None:
    """Verify complete_todo appends [completed::YYYY-MM-DD] to the task line."""
    add_todo_item(task="Submit quarterly tax form", project="Inbox")
    res = complete_todo(task_query="quarterly tax", project="Inbox")
    assert res["status"] == "success"
    today_str = datetime.now().strftime("%Y-%m-%d")
    assert f"[completed::{today_str}]" in res["task"]
    assert "- [x]" in res["task"]


def test_list_todos_contract_fields() -> None:
    """Verify list_todos returns both status and completed, and due and due_date."""
    add_todo_item(task="Verify contract fields #qa", project="Inbox", due_date="2026-09-20")
    pending = list_todos(project="Inbox", status="pending")
    assert len(pending) >= 1
    t = [item for item in pending if "Verify contract fields" in item["text"]][0]
    assert t["status"] == "pending"
    assert t["completed"] is False
    assert t["due"] == "2026-09-20"
    assert t["due_date"] == "2026-09-20"
    assert "qa" in t["tags"]


def test_prune_old_completed_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify completed tasks older than 14 days are auto-deleted while recent tasks remain."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AETHER_VAULT_DIR", str(vault_dir))

    today = datetime.now().date()
    old_date = (today - timedelta(days=20)).strftime("%Y-%m-%d")
    recent_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")

    inbox_content = (
        f"# Inbox\n\n"
        f"- [ ] Active pending task\n"
        f"- [x] Old completed task [completed::{old_date}]\n"
        f"- [x] Recent completed task [completed::{recent_date}]\n"
    )
    inbox_file = vault_dir / "Inbox.md"
    inbox_file.write_text(inbox_content, encoding="utf-8")

    # Run auto-pruning with 14-day cutoff
    pruned_count = prune_old_completed_tasks(max_age_days=14)
    assert pruned_count == 1

    updated_content = inbox_file.read_text(encoding="utf-8")
    assert "Active pending task" in updated_content
    assert "Recent completed task" in updated_content
    assert "Old completed task" not in updated_content

    # Calling list_todos triggers auto-pruning and returns only the recent completed task
    completed = list_todos(project="Inbox", status="completed")
    assert len(completed) == 1
    assert completed[0]["text"] == "Recent completed task"


def test_task_priority_explicit_and_deduced() -> None:
    """Verify explicit priority and heuristic deduction from task text."""
    # Explicit urgent priority
    res1 = add_todo_item(task="Critical server crash recovery", project="Inbox", priority="urgent")
    assert res1["status"] == "success"
    assert res1["priority"] == "urgent"

    # Inferred urgent from text
    res2 = add_todo_item(task="Fix production bug immediately asap", project="Inbox")
    assert res2["status"] == "success"
    assert res2["priority"] == "urgent"

    # Explicit important priority
    res3 = add_todo_item(task="Study for SC3021 midterm exam", project="Inbox", priority="important")
    assert res3["status"] == "success"
    assert res3["priority"] == "important"

    # Inferred important from text
    res4 = add_todo_item(task="Prepare key task presentation for board", project="Inbox")
    assert res4["status"] == "success"
    assert res4["priority"] == "important"

    # Default normal priority
    res5 = add_todo_item(task="Buy milk and groceries", project="Inbox")
    assert res5["status"] == "success"
    assert res5["priority"] == "normal"

    # List all and verify priority metadata and clean text
    all_todos = list_todos(project="Inbox", status="all")
    task_map = {t["text"]: t["priority"] for t in all_todos}

    assert task_map["Critical server crash recovery"] == "urgent"
    assert task_map["Fix production bug immediately asap"] == "urgent"
    assert task_map["Study for SC3021 midterm exam"] == "important"
    assert task_map["Prepare key task presentation for board"] == "important"
    assert task_map["Buy milk and groceries"] == "normal"


def test_task_priority_filtering() -> None:
    """Verify list_todos filters correctly by priority."""
    add_todo_item(task="Urgent ticket 1", project="Inbox", priority="urgent")
    add_todo_item(task="Important ticket 2", project="Inbox", priority="important")
    add_todo_item(task="Normal ticket 3", project="Inbox", priority="normal")

    urgent_tasks = list_todos(project="Inbox", status="all", priority="urgent")
    assert len(urgent_tasks) == 1
    assert urgent_tasks[0]["text"] == "Urgent ticket 1"
    assert urgent_tasks[0]["priority"] == "urgent"

    important_tasks = list_todos(project="Inbox", status="all", priority="important")
    assert len(important_tasks) == 1
    assert important_tasks[0]["text"] == "Important ticket 2"
    assert important_tasks[0]["priority"] == "important"

    normal_tasks = list_todos(project="Inbox", status="all", priority="normal")
    assert len(normal_tasks) == 1
    assert normal_tasks[0]["text"] == "Normal ticket 3"
    assert normal_tasks[0]["priority"] == "normal"


def test_update_todo_priority() -> None:
    """Verify updating the priority of an existing task inline in the markdown file."""
    add_todo_item(task="Review PR #42", project="Inbox", priority="normal")

    # Update to urgent
    up_res = update_todo_priority(task_query="Review PR #42", priority="urgent", project="Inbox")
    assert up_res["status"] == "success"
    assert up_res["priority"] == "urgent"
    assert "priority::urgent" in up_res["task"]

    # Verify via list_todos
    todos = list_todos(project="Inbox", status="all")
    pr_task = next(t for t in todos if "Review PR #42" in t["text"])
    assert pr_task["priority"] == "urgent"

    # Update to important
    up_res2 = update_todo_priority(task_query="Review PR #42", priority="important", project="Inbox")
    assert up_res2["status"] == "success"
    assert up_res2["priority"] == "important"
    assert "priority::important" in up_res2["task"]

    todos2 = list_todos(project="Inbox", status="all")
    pr_task2 = next(t for t in todos2 if "Review PR #42" in t["text"])
    assert pr_task2["priority"] == "important"

