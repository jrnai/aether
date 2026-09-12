"""Unit tests for real-time token streaming across OllamaClient, AgentLoop, and Web Server."""
import json
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from src.agent.loop import AgentLoop
from src.client.ollama_client import OllamaClient
from src.web.server import create_app


def test_ollama_client_chat_stream() -> None:
    client = OllamaClient()
    mock_lines = [
        json.dumps({"message": {"role": "assistant", "content": "Hello"}, "done": False}).encode("utf-8") + b"\n",
        json.dumps({"message": {"role": "assistant", "content": " world"}, "done": False}).encode("utf-8") + b"\n",
        json.dumps({"message": {"role": "assistant", "content": "!"}, "done": True, "eval_count": 3}).encode("utf-8") + b"\n",
    ]
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_lines

    with patch("urllib.request.urlopen", return_value=mock_resp), patch.object(client, "list_models", return_value=["qwen2.5:7b-instruct"]):
        events = list(client.chat_stream(messages=[{"role": "user", "content": "hi"}], model="qwen2.5:7b-instruct"))

    tokens = [e["delta"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "Hello world!"
    done_ev = next(e for e in events if e["type"] == "done")
    assert done_ev["message"]["content"] == "Hello world!"


def test_agent_loop_run_turn_stream() -> None:
    mock_client = MagicMock(spec=OllamaClient)
    mock_client.chat_stream.return_value = iter([
        {"type": "token", "delta": "Streaming "},
        {"type": "token", "delta": "response."},
        {"type": "done", "message": {"role": "assistant", "content": "Streaming response."}},
    ])

    loop = AgentLoop(client=mock_client, model="qwen2.5:7b-instruct")
    events = list(loop.run_turn_stream("Hello"))

    types = [e["type"] for e in events]
    assert "token" in types
    assert "done" in types

    tokens = [e["delta"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "Streaming response."


def test_agent_loop_run_turn_stream_with_tool() -> None:
    mock_client = MagicMock(spec=OllamaClient)

    step1_events = [
        {"type": "tool_calls", "tool_calls": [{"id": "call_1", "function": {"name": "sample_tool", "arguments": {}}}]},
        {"type": "done", "message": {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "sample_tool", "arguments": {}}}]}},
    ]
    step2_events = [
        {"type": "token", "delta": "Tool executed successfully."},
        {"type": "done", "message": {"role": "assistant", "content": "Tool executed successfully."}},
    ]

    mock_client.chat_stream.side_effect = [iter(step1_events), iter(step2_events)]

    loop = AgentLoop(client=mock_client, model="qwen2.5:7b-instruct")
    loop.register_tool(
        name="sample_tool",
        description="A sample test tool",
        parameters={"type": "object", "properties": {}},
        func=lambda: {"result": "ok"},
        safe=True,
    )

    events = list(loop.run_turn_stream("Run sample tool"))

    types = [e["type"] for e in events]
    assert "tool_start" in types
    assert "tool_end" in types
    assert "token" in types
    assert "done" in types


def test_web_server_chat_stream_endpoint() -> None:
    app = create_app()
    client = TestClient(app)

    with patch("src.client.ollama_client.OllamaClient.is_connected", return_value=True), \
         patch("src.web.server.resolve_model_for_task", return_value="qwen2.5:7b-instruct"), \
         patch("src.agent.loop.AgentLoop.run_turn_stream", return_value=iter([
             {"type": "token", "delta": "Hello "},
             {"type": "token", "delta": "user!"},
             {"type": "done", "full_text": "Hello user!", "model": "qwen2.5:7b-instruct"},
         ])):

        response = client.post("/api/chat/stream", json={"message": "Hi"})
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = response.text
        assert "data: " in body
        assert "Hello " in body
        assert "user!" in body
