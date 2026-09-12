"""Unit tests for SafetyGuard and Human-in-the-Loop interceptor."""
import json
from src.agent.guardrails import SafetyGuard, ToolSafetyAction


def test_safe_tool_does_not_require_approval() -> None:
    guard = SafetyGuard()
    guard.register_tool("search_notes", safe=True)

    assert guard.is_safe("search_notes") is True
    assert guard.requires_approval("search_notes") is False

    authorized, cancel_payload = guard.check_and_authorize("search_notes", {"query": "todo"})
    assert authorized is True
    assert cancel_payload is None


def test_mutating_tool_triggers_approval_accepted() -> None:
    calls = []

    def mock_confirm(tool_name: str, args: dict) -> bool:
        calls.append((tool_name, args))
        return True

    guard = SafetyGuard(confirmation_callback=mock_confirm)
    guard.register_tool("create_event", safe=False)

    assert guard.is_safe("create_event") is False
    assert guard.requires_approval("create_event") is True

    authorized, cancel_payload = guard.check_and_authorize("create_event", {"title": "Meeting"})
    assert authorized is True
    assert cancel_payload is None
    assert len(calls) == 1
    assert calls[0] == ("create_event", {"title": "Meeting"})


def test_mutating_tool_triggers_approval_rejected() -> None:
    def mock_reject(tool_name: str, args: dict) -> bool:
        return False

    guard = SafetyGuard(confirmation_callback=mock_reject)
    guard.register_tool("delete_note", safe=False)

    authorized, cancel_payload = guard.check_and_authorize("delete_note", {"file": "secret.md"})
    assert authorized is False
    assert cancel_payload is not None

    parsed = json.loads(cancel_payload)
    assert parsed["status"] == "cancelled"
    assert "cancelled by the human operator" in parsed["message"]


def test_unregistered_tool_defaults_to_unsafe() -> None:
    # Any unknown tool should default to unsafe
    guard = SafetyGuard(confirmation_callback=lambda name, args: False)
    assert guard.is_safe("unknown_tool") is False

    authorized, cancel_payload = guard.check_and_authorize("unknown_tool", {})
    assert authorized is False


def test_audit_logger_called() -> None:
    logged_actions: list[ToolSafetyAction] = []

    guard = SafetyGuard(
        confirmation_callback=lambda name, args: True,
        audit_logger=lambda action: logged_actions.append(action),
    )
    guard.register_tool("stage_draft", safe=False)
    guard.register_tool("read_note", safe=True)

    guard.check_and_authorize("read_note", {"path": "a.md"})
    guard.check_and_authorize("stage_draft", {"to": "bob@example.com"})

    assert len(logged_actions) == 2
    assert logged_actions[0].tool_name == "read_note"
    assert logged_actions[0].is_safe is True
    assert logged_actions[1].tool_name == "stage_draft"
    assert logged_actions[1].is_safe is False
    assert logged_actions[1].user_approved is True


def test_send_email_mutating_classification() -> None:
    from src.mcp_bridge.manager import MUTATING_KEYWORDS

    # Verify 'send' is in mutating keywords
    assert "send" in MUTATING_KEYWORDS
    tool_name = "send_email"
    is_safe = not any(kw in tool_name.lower() for kw in MUTATING_KEYWORDS)
    assert is_safe is False

    # Verify SafetyGuard intercepts send_email
    intercepted = []
    guard = SafetyGuard(confirmation_callback=lambda name, args: intercepted.append((name, args)) or True)
    guard.register_tool("send_email", safe=False)

    authorized, _ = guard.check_and_authorize(
        "send_email",
        {"to": "target@example.com", "subject": "Hello", "body": "Test"},
    )
    assert authorized is True
    assert len(intercepted) == 1
    assert intercepted[0][0] == "send_email"
    assert intercepted[0][1]["to"] == "target@example.com"
