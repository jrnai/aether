"""Unit tests for ContextManager, token estimation, temporal grounding, and history pruning."""
from datetime import datetime
from src.agent.context_manager import (
    ContextManager,
    compress_tool_payload,
    estimate_messages_tokens,
    estimate_tokens,
    generate_system_prompt,
    prune_history,
    wrap_untrusted_content,
)


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0
    assert estimate_tokens("hello") > 0
    assert estimate_tokens("a" * 400) >= 100


def test_temporal_grounding_in_system_prompt() -> None:
    prompt = generate_system_prompt()
    now = datetime.now()
    year_str = str(now.year)
    weekday_str = now.strftime("%A")

    assert "CURRENT TEMPORAL CONTEXT:" in prompt
    assert year_str in prompt
    assert weekday_str in prompt
    assert "CORE OPERATIONAL DIRECTIVES:" in prompt


def test_compress_tool_payload() -> None:
    short_text = "Status: success"
    assert compress_tool_payload(short_text, max_chars=100) == short_text

    long_text = "x" * 1000
    compressed = compress_tool_payload(long_text, max_chars=200)
    assert len(compressed) <= 250
    assert "Truncated" in compressed


def test_wrap_untrusted_content() -> None:
    wrapped = wrap_untrusted_content("Hello from email", source="email", sender="alice@example.com")
    assert "<untrusted_content source=\"email\" sender=\"alice@example.com\">" in wrapped
    assert "Hello from email" in wrapped
    assert "</untrusted_content>" in wrapped


def test_prune_history_preserves_system_and_initial_user() -> None:
    messages = [
        {"role": "system", "content": "You are Aether."},
        {"role": "user", "content": "Initial user goal: plan my day."},
    ]
    # Add many intermediate turns to exceed max_tokens
    for i in range(50):
        messages.append({"role": "assistant", "content": f"Intermediate reply {i} " + "data " * 100})
        messages.append({"role": "user", "content": f"Follow-up question {i} " + "query " * 100})

    assert estimate_messages_tokens(messages) > 6500

    pruned = prune_history(messages, max_tokens=1000)

    # Invariants
    assert len(pruned) < len(messages)
    assert pruned[0]["role"] == "system"
    assert pruned[0]["content"] == "You are Aether."
    assert pruned[1]["role"] == "user"
    assert "Initial user goal" in pruned[1]["content"]
    assert estimate_messages_tokens(pruned) <= 1200


def test_context_manager_class() -> None:
    cm = ContextManager(max_context_tokens=8192, prune_threshold_tokens=5000)
    system_prompt = cm.get_grounded_system_prompt()
    assert "CURRENT TEMPORAL CONTEXT:" in system_prompt

    short_msg = [{"role": "user", "content": "Hi"}]
    prepared = cm.prepare_messages(short_msg)
    assert len(prepared) == 1

    tool_res = cm.compress_tool_result("A" * 2000)
    assert "Truncated" in tool_res
