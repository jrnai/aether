"""Unit tests for task-specialized model routing and RTX 5060 optimizations."""
from unittest.mock import MagicMock, patch
import pytest

from src.agent.context_manager import ContextManager, DEFAULT_MAX_CONTEXT_TOKENS, DEFAULT_PRUNE_THRESHOLD_TOKENS
from src.client.ollama_client import OllamaClient
from src.config import get_config, reset_config
from src.web.server import (
    is_reasoning_prompt,
    resolve_model_for_task,
)


@pytest.fixture(autouse=True)
def reset_cfg():
    reset_config()
    import src.web.server as srv
    srv._active_model = None
    srv._is_auto_route = True
    yield
    reset_config()
    srv._active_model = None
    srv._is_auto_route = True


def test_is_reasoning_prompt():
    """Verify heuristic classification of reasoning and logic prompts."""
    assert is_reasoning_prompt("Solve this logic puzzle for me step by step") is True
    assert is_reasoning_prompt("Can you derive the mathematical proof for Fermat's theorem?") is True
    assert is_reasoning_prompt("What is the answer to this riddle?") is True
    assert is_reasoning_prompt("Calculate the optimal algorithm complexity") is True

    # Non-reasoning prompts
    assert is_reasoning_prompt("What events do I have on my calendar tomorrow?") is False
    assert is_reasoning_prompt("Summarize my pending tasks") is False
    assert is_reasoning_prompt("Write a short email to John") is False
    assert is_reasoning_prompt("") is False


def test_resolve_model_for_task_coding():
    """Coding tasks must resolve to qwen2.5-coder:7b."""
    model = resolve_model_for_task(task_type="coding")
    assert "coder" in model.lower()
    assert model == "qwen2.5-coder:7b"


def test_resolve_model_for_task_briefing():
    """Briefings must resolve to general/agentic model."""
    model = resolve_model_for_task(task_type="briefing")
    assert "instruct" in model.lower() or "qwen" in model.lower()
    assert model == "qwen2.5:7b-instruct"


def test_resolve_model_for_task_chat_general():
    """General chat prompts should route to qwen2.5:7b-instruct."""
    model = resolve_model_for_task(task_type="chat", prompt="What is the weather like today?")
    assert model == "qwen2.5:7b-instruct"


def test_resolve_model_for_task_chat_reasoning_auto_route():
    """Logic and puzzle prompts should route to deepseek-r1:7b when available."""
    mock_client = MagicMock(spec=OllamaClient)
    mock_client.list_models.return_value = ["qwen2.5-coder:7b", "qwen2.5:7b-instruct", "deepseek-r1:7b"]

    model = resolve_model_for_task(
        task_type="chat",
        prompt="Solve this logic puzzle step by step",
        client=mock_client,
    )
    assert model == "deepseek-r1:7b"


def test_resolve_model_for_task_chat_reasoning_fallback_when_missing():
    """When deepseek-r1:7b is not installed, route falls back gracefully to general_model."""
    mock_client = MagicMock(spec=OllamaClient)
    mock_client.list_models.return_value = ["qwen2.5-coder:7b", "qwen2.5:7b-instruct"]

    model = resolve_model_for_task(
        task_type="chat",
        prompt="Solve this logic puzzle step by step",
        client=mock_client,
    )
    assert model == "qwen2.5:7b-instruct"


def test_resolve_model_for_task_manual_override():
    """When auto-routing is disabled, user's chosen model overrides defaults."""
    import src.web.server as srv
    srv._is_auto_route = False
    srv._active_model = "my-custom-model:latest"

    model = resolve_model_for_task(task_type="chat", prompt="Hello world")
    assert model == "my-custom-model:latest"


def test_ollama_client_passes_num_ctx():
    """Verify OllamaClient transmits num_ctx inside options."""
    client = OllamaClient(default_num_ctx=16384)

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"message": {"role": "assistant", "content": "Done"}}'
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        # Mock list_models so it doesn't fail
        with patch.object(client, "list_models", return_value=["qwen2.5:7b-instruct"]):
            client.chat(messages=[{"role": "user", "content": "hi"}], num_ctx=16384)

        # Inspect request payload
        req_arg = mock_urlopen.call_args[0][0]
        import json
        payload = json.loads(req_arg.data.decode("utf-8"))
        assert payload["options"]["num_ctx"] == 16384


def test_context_manager_scaled_defaults():
    """Verify context manager constants reflect the 16k context window."""
    assert DEFAULT_MAX_CONTEXT_TOKENS == 16384
    assert DEFAULT_PRUNE_THRESHOLD_TOKENS == 13100
    cm = ContextManager()
    assert cm.max_context_tokens == 16384
    assert cm.prune_threshold_tokens == 13100


def test_resolve_model_for_task_vision_with_has_images():
    """Tasks with attached images must route to the multimodal vision model."""
    mock_client = MagicMock(spec=OllamaClient)
    mock_client.list_models.return_value = ["qwen2.5:7b-instruct", "qwen2.5vl:7b"]

    model = resolve_model_for_task(
        task_type="chat",
        prompt="Describe this diagram",
        client=mock_client,
        has_images=True,
    )
    assert model == "qwen2.5vl:7b"


def test_resolve_model_for_task_vision_fallback_to_installed_vl():
    """If default vision model is not present, find any installed VL/vision model."""
    mock_client = MagicMock(spec=OllamaClient)
    mock_client.list_models.return_value = ["qwen2.5:7b-instruct", "llava:7b"]

    model = resolve_model_for_task(
        task_type="vision",
        prompt="Read this chart",
        client=mock_client,
    )
    assert model == "llava:7b"
