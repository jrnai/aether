"""Unit tests for the OllamaClient interface using mocked HTTP responses."""
import json
import urllib.error
from unittest.mock import MagicMock, patch
import pytest

from src.client.ollama_client import OllamaClient


def test_ollama_client_is_connected_true() -> None:
    client = OllamaClient()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert client.is_connected() is True


def test_ollama_client_is_connected_false_on_error() -> None:
    client = OllamaClient()

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Refused")):
        assert client.is_connected() is False


def test_ollama_client_list_models() -> None:
    client = OllamaClient()
    mock_data = json.dumps({"models": [{"name": "qwen2.5:14b"}, {"name": "llama3.1:8b"}]}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = mock_data

    with patch("urllib.request.urlopen", return_value=mock_resp):
        models = client.list_models()
        assert models == ["qwen2.5:14b", "llama3.1:8b"]


def test_ollama_client_chat_success() -> None:
    client = OllamaClient()
    mock_message = {
        "role": "assistant",
        "content": "Hello world",
        "tool_calls": []
    }
    mock_payload = json.dumps({"message": mock_message}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = mock_payload

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.chat(messages=[{"role": "user", "content": "Hi"}])
        assert res["role"] == "assistant"
        assert res["content"] == "Hello world"


def test_ollama_client_chat_connection_error() -> None:
    client = OllamaClient()

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        with pytest.raises(ConnectionError, match="Cannot connect to Ollama"):
            client.chat(messages=[{"role": "user", "content": "Hi"}])


def test_ollama_client_chat_http_error_model_not_found() -> None:
    client = OllamaClient()
    http_err = urllib.error.HTTPError(
        url="http://127.0.0.1:11434/api/chat",
        code=404,
        msg="Not Found",
        hdrs={},
        fp=None,
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(RuntimeError, match="Model '.*' not found in local Ollama instance"):
            client.chat(messages=[{"role": "user", "content": "Hi"}])

