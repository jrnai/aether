"""Unit tests for Dynamic Tool Masking in AgentLoop."""
from unittest.mock import MagicMock
import pytest

from src.agent.loop import (
    AgentLoop,
    detect_intent_domains,
    get_tool_domain,
    TOOL_DOMAINS,
)


def test_detect_intent_domains_coding() -> None:
    queries = [
        "inspect src/main.py and fix the bug",
        "run pytest on the test suite",
        "can you check git status and diff the files?",
        "refactor this function in app.py",
    ]
    for q in queries:
        domains = detect_intent_domains(q)
        assert "files_and_coding" in domains, f"Failed for: {q}"
        assert "calendar" not in domains
        assert "mail" not in domains


def test_detect_intent_domains_calendar() -> None:
    queries = [
        "what meetings do I have tomorrow?",
        "check my calendar for upcoming events",
        "find free slots on Friday afternoon",
        "schedule a sync at 2pm",
    ]
    for q in queries:
        domains = detect_intent_domains(q)
        assert "calendar" in domains, f"Failed for: {q}"
        assert "files_and_coding" not in domains
        assert "mail" not in domains


def test_detect_intent_domains_mail() -> None:
    queries = [
        "check my unread emails in the inbox",
        "draft an email to Sarah with subject Project Update",
        "did I get any mail from Bob?",
    ]
    for q in queries:
        domains = detect_intent_domains(q)
        assert "mail" in domains, f"Failed for: {q}"
        assert "files_and_coding" not in domains
        assert "calendar" not in domains


def test_detect_intent_domains_notes() -> None:
    queries = [
        "add a todo to submit invoice",
        "show me my active tasks and checklist",
        "read my daily review note",
    ]
    for q in queries:
        domains = detect_intent_domains(q)
        assert "notes" in domains, f"Failed for: {q}"
        assert "files_and_coding" not in domains


def test_detect_intent_domains_multi_domain() -> None:
    query = "check my calendar for tomorrow and add a todo for the client meeting"
    domains = detect_intent_domains(query)
    assert "calendar" in domains
    assert "notes" in domains
    assert "files_and_coding" not in domains


def test_detect_intent_domains_ambiguous() -> None:
    query = "Hello, who are you and what can you help me with?"
    domains = detect_intent_domains(query)
    assert len(domains) == 0


def test_get_tool_domain() -> None:
    assert get_tool_domain("files_read_file") == "files_and_coding"
    assert get_tool_domain("calendar_list_events") == "calendar"
    assert get_tool_domain("mail_fetch_unread") == "mail"
    assert get_tool_domain("notes_add_todo") == "notes"
    assert get_tool_domain("search_web") == "web"
    assert get_tool_domain("unknown_custom_tool") is None


def test_dynamic_tool_masking_pruning() -> None:
    mock_client = MagicMock()
    loop = AgentLoop(client=mock_client, dynamic_tool_masking=True)

    # Register sample tools across all domains
    loop.register_tool("files_read_file", "Read a file", {}, lambda: None)
    loop.register_tool("files_write_file", "Write a file", {}, lambda: None)
    loop.register_tool("files_run_command", "Run terminal command", {}, lambda: None)
    loop.register_tool("calendar_list_events", "List events", {}, lambda: None)
    loop.register_tool("calendar_create_event", "Create event", {}, lambda: None)
    loop.register_tool("mail_list_emails", "List emails", {}, lambda: None)
    loop.register_tool("notes_list_todos", "List todos", {}, lambda: None)
    loop.register_tool("custom_core_tool", "Always active", {}, lambda: None)

    assert len(loop.tools_schema) == 8

    # 1. Coding query should only include files_and_coding + unclassified core tools
    coding_schema = loop.get_active_tools_schema("inspect main.py and run pytest")
    coding_names = {t["function"]["name"] for t in coding_schema}
    assert "files_read_file" in coding_names
    assert "files_write_file" in coding_names
    assert "files_run_command" in coding_names
    assert "custom_core_tool" in coding_names
    assert "calendar_list_events" not in coding_names
    assert "calendar_create_event" not in coding_names
    assert "mail_list_emails" not in coding_names
    assert "notes_list_todos" not in coding_names
    assert len(coding_schema) == 4

    # 2. Calendar query should only include calendar + core tools
    cal_schema = loop.get_active_tools_schema("what meetings do I have tomorrow?")
    cal_names = {t["function"]["name"] for t in cal_schema}
    assert "calendar_list_events" in cal_names
    assert "calendar_create_event" in cal_names
    assert "custom_core_tool" in cal_names
    assert "files_read_file" not in cal_names
    assert len(cal_schema) == 3

    # 3. Ambiguous query should retain all registered tools
    ambig_schema = loop.get_active_tools_schema("help me plan my morning")
    # "morning" triggers calendar, so let's test a purely non-domain greeting
    greeting_schema = loop.get_active_tools_schema("hello there, good to see you")
    assert len(greeting_schema) == 8


def test_dynamic_tool_masking_turn_preservation() -> None:
    mock_client = MagicMock()
    loop = AgentLoop(client=mock_client, dynamic_tool_masking=True)

    loop.register_tool("files_read_file", "Read a file", {}, lambda: None)
    loop.register_tool("files_patch_file", "Patch a file", {}, lambda: None)
    loop.register_tool("calendar_list_events", "List events", {}, lambda: None)

    # Even if current query was vague, if active_domains contains "files_and_coding",
    # those tools are preserved for the subsequent step
    step2_schema = loop.get_active_tools_schema("ok continue", active_domains={"files_and_coding"})
    names = {t["function"]["name"] for t in step2_schema}
    assert "files_read_file" in names
    assert "files_patch_file" in names
    assert "calendar_list_events" not in names


def test_dynamic_tool_masking_disabled() -> None:
    mock_client = MagicMock()
    loop = AgentLoop(client=mock_client, dynamic_tool_masking=False)

    loop.register_tool("files_read_file", "Read a file", {}, lambda: None)
    loop.register_tool("calendar_list_events", "List events", {}, lambda: None)

    # With masking disabled, always returns all tools
    schema = loop.get_active_tools_schema("inspect main.py")
    assert len(schema) == 2
