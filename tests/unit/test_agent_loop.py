"""Unit tests for the AgentLoop state machine and tool-calling execution."""
from typing import Any
from src.agent.guardrails import SafetyGuard
from src.agent.loop import AgentLoop


class MockOllamaClient:
    """Mock LLM client returning scripted responses for deterministic testing."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.call_history: list[list[dict[str, Any]]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        self.call_history.append(list(messages))
        if not self.responses:
            return {"role": "assistant", "content": "Default mock response"}
        return self.responses.pop(0)


def test_agent_loop_text_response_only() -> None:
    mock_client = MockOllamaClient([
        {"role": "assistant", "content": "Hello! How can I help you today?"}
    ])
    loop = AgentLoop(client=mock_client)
    res = loop.run_turn("Hi there!")

    assert res == "Hello! How can I help you today?"
    assert len(loop.messages) == 3  # system, user, assistant
    assert loop.messages[0]["role"] == "system"
    assert loop.messages[1]["role"] == "user"
    assert loop.messages[2]["role"] == "assistant"


def test_agent_loop_safe_tool_execution() -> None:
    # 1st LLM call: returns tool call to search_notes
    # 2nd LLM call: returns final answer based on tool result
    mock_client = MockOllamaClient([
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "search_notes",
                        "arguments": {"query": "groceries"},
                    }
                }
            ],
        },
        {
            "role": "assistant",
            "content": "You have a grocery list note with apples and milk.",
        },
    ])

    search_called_with = []

    def mock_search(query: str) -> list[str]:
        search_called_with.append(query)
        return ["Apples", "Milk"]

    loop = AgentLoop(client=mock_client)
    loop.register_tool(
        name="search_notes",
        description="Search notes by query",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        func=mock_search,
        safe=True,
    )

    res = loop.run_turn("What is on my grocery list?")
    assert res == "You have a grocery list note with apples and milk."
    assert search_called_with == ["groceries"]

    # History should contain: system, user, assistant(tool_calls), tool(result), assistant(final)
    roles = [m["role"] for m in loop.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    assert "Apples" in loop.messages[3]["content"]


def test_agent_loop_mutating_tool_denied_by_user() -> None:
    # 1st call: request mutating tool
    # 2nd call: LLM receives cancellation payload and responds gracefully
    mock_client = MockOllamaClient([
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "create_event",
                        "arguments": {"title": "Doctor Appointment"},
                    }
                }
            ],
        },
        {
            "role": "assistant",
            "content": "Understood, I have cancelled the calendar appointment creation.",
        },
    ])

    event_created = []

    def mock_create(title: str) -> str:
        event_created.append(title)
        return "event_id_123"

    # Confirmation callback rejects the action
    guard = SafetyGuard(confirmation_callback=lambda name, args: False)
    loop = AgentLoop(client=mock_client, guard=guard)
    loop.register_tool(
        name="create_event",
        description="Create calendar event",
        parameters={"type": "object", "properties": {"title": {"type": "string"}}},
        func=mock_create,
        safe=False,
    )

    res = loop.run_turn("Schedule a doctor appointment")
    assert res == "Understood, I have cancelled the calendar appointment creation."
    assert len(event_created) == 0  # Tool must NOT be called

    # Tool message contains cancellation
    tool_msg = loop.messages[3]
    assert tool_msg["role"] == "tool"
    assert "cancelled by the human operator" in tool_msg["content"]


def test_agent_loop_max_steps_guard() -> None:
    # Model endlessly loops requesting tool calls
    infinite_tool_call = {
        "role": "assistant",
        "tool_calls": [{"function": {"name": "dummy_tool", "arguments": {}}}],
    }
    mock_client = MockOllamaClient([infinite_tool_call] * 10)

    loop = AgentLoop(client=mock_client, max_steps=3)
    loop.register_tool("dummy_tool", "Dummy", {}, lambda: "ok", safe=True)

    res = loop.run_turn("Loop forever")
    assert "maximum tool execution limit" in res


def test_agent_loop_resolves_fuzzy_tool_name() -> None:
    # Model emits 'fileslistfiles' (missing underscores and alias)
    tool_call_response = {
        "role": "assistant",
        "content": '{"name": "fileslistfiles", "arguments": {"path": "."}}',
    }
    final_response = {
        "role": "assistant",
        "content": "Found 3 files in workspace.",
    }
    mock_client = MockOllamaClient([tool_call_response, final_response])

    executed = []
    def mock_list(path: str = ".") -> str:
        executed.append(path)
        return "file1.py, file2.py, file3.py"

    loop = AgentLoop(client=mock_client)
    loop.register_tool(
        name="files_list_directory",
        description="List files in directory",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        func=mock_list,
        safe=True,
    )

    res = loop.run_turn("What files do I have?")
    assert res == "Found 3 files in workspace."
    assert len(executed) == 1
    assert executed[0] == "."


def test_agent_loop_resolves_set_workspace_alias() -> None:
    # Model emits 'setworkspace'
    tool_call_response = {
        "role": "assistant",
        "content": '```json\n{"name": "setworkspace", "arguments": {"path": "Projects"}}\n```',
    }
    final_response = {
        "role": "assistant",
        "content": "Active workspace is now Projects.",
    }
    mock_client = MockOllamaClient([tool_call_response, final_response])

    executed = []
    def mock_set_ws(path: str) -> dict:
        executed.append(path)
        return {"status": "success", "workspace_root": path}

    loop = AgentLoop(client=mock_client)
    loop.register_tool(
        name="files_set_workspace",
        description="Set workspace root",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        func=mock_set_ws,
        safe=True,
    )

    res = loop.run_turn("Move to Projects")
    assert res == "Active workspace is now Projects."
    assert len(executed) == 1
    assert executed[0] == "Projects"


def test_agent_loop_nested_json_tool_call_in_text() -> None:
    # Model returns conversational text containing a nested JSON tool call
    tool_call_response = {
        "role": "assistant",
        "content": 'I will switch the workspace for you now: {"name": "files_set_workspace", "arguments": {"path": "C:\\\\Users\\\\jrrya\\\\Projects"}}',
    }
    final_response = {
        "role": "assistant",
        "content": "Successfully switched to Projects.",
    }
    mock_client = MockOllamaClient([tool_call_response, final_response])

    executed = []
    def mock_set_ws(path: str) -> dict:
        executed.append(path)
        return {"status": "success", "workspace_root": path}

    loop = AgentLoop(client=mock_client)
    loop.register_tool(
        name="files_set_workspace",
        description="Set workspace root",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        func=mock_set_ws,
        safe=True,
    )

    res = loop.run_turn("please switch to C:\\Users\\jrrya\\Projects")
    assert res == "Successfully switched to Projects."
    assert len(executed) == 1
    assert "Projects" in executed[0]


def test_agent_loop_web_search_alias() -> None:
    # Model emits 'websearch' which maps to 'search_web'
    tool_call_response = {
        "role": "assistant",
        "content": '{"name": "websearch", "arguments": {"query": "weather today"}}',
    }
    final_response = {
        "role": "assistant",
        "content": "It is sunny today.",
    }
    mock_client = MockOllamaClient([tool_call_response, final_response])

    executed = []
    def mock_search(query: str) -> list[dict]:
        executed.append(query)
        return [{"title": "Weather", "url": "https://example.com"}]

    loop = AgentLoop(client=mock_client)
    loop.register_tool(
        name="search_web",
        description="Search DuckDuckGo",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        func=mock_search,
        safe=True,
    )

    res = loop.run_turn("What is the weather?")
    assert res == "It is sunny today."
    assert len(executed) == 1
    assert executed[0] == "weather today"


def test_agent_loop_multimodal_images() -> None:
    mock_client = MockOllamaClient([
        {"role": "assistant", "content": "This image shows a bar chart of Q3 earnings."}
    ])
    loop = AgentLoop(client=mock_client)
    res = loop.run_turn(
        user_input="Analyze this chart",
        images=["iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="],
    )
    assert "bar chart" in res
    user_msg = loop.messages[1]
    assert user_msg["role"] == "user"
    assert "images" in user_msg
    assert len(user_msg["images"]) == 1
    assert user_msg["images"][0].startswith("iVBORw0")


def test_agent_loop_subsequent_turn_strips_images_for_text_model() -> None:
    """Subsequent turns on a text-only model must strip previous turns' images."""
    mock_client = MockOllamaClient([
        {"role": "assistant", "content": "I see a chart."},
        {"role": "assistant", "content": "The weather is sunny."},
    ])
    loop = AgentLoop(model="qwen2.5:7b-instruct", client=mock_client)
    # Turn 1: with image
    loop.run_turn(
        user_input="Analyze chart",
        images=["base64img"],
    )
    # Turn 2: text only
    loop.run_turn(user_input="How is the weather today?")
    # Inspect what messages were passed to mock_client in Turn 2
    turn2_messages = mock_client.call_history[-1]
    for msg in turn2_messages:
        assert "images" not in msg, f"Message should not have 'images' key for text model: {msg}"


def test_agent_loop_sanitizes_generated_image_url() -> None:
    """Agent loop must sanitize hallucinated domain prefixes in front of /api/generated_images/."""
    mock_client = MockOllamaClient([
        {"role": "assistant", "content": "Here is your image:\n\n![](https://example.com/api/generated_images/test_image.png)"}
    ])
    loop = AgentLoop(client=mock_client)
    res = loop.run_turn("create an image")
    assert "https://example.com" not in res
    assert "![](/api/generated_images/test_image.png)" in res


def test_agent_loop_prunes_hallucinated_kwargs() -> None:
    """Agent loop must prune hallucinated kwargs that do not exist in tool signatures."""
    captured = {}
    def sample_tool(title: str, start_iso: str = "") -> dict:
        captured["title"] = title
        captured["start_iso"] = start_iso
        return {"status": "success", "title": title}

    loop = AgentLoop()
    # Call with hallucinated kwargs that do not exist in sample_tool
    res, is_err = loop._invoke_tool_safely(
        sample_tool,
        "sample_tool",
        {"title": "Task", "start_iso": "10:00", "duration_minutes": 30, "fake_param": 123},
    )
    assert not is_err
    assert res["status"] == "success"
    assert captured == {"title": "Task", "start_iso": "10:00"}





