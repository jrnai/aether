"""Live verification test against running Ollama instance."""
from src.client.ollama_client import OllamaClient


def test_live_qwen_tool_call() -> None:
    client = OllamaClient(default_model="qwen2.5:7b-instruct")
    assert client.is_connected(), "Ollama should be reachable on http://127.0.0.1:11434"

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]

    response = client.chat(
        messages=[{"role": "user", "content": "What is the weather in Tokyo?"}],
        tools=tools,
        model="qwen2.5:7b-instruct",
    )

    print("\nLive model response:", response)
    tool_calls = response.get("tool_calls", [])
    assert len(tool_calls) > 0, f"Model should emit a tool call, got: {response}"
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert "Tokyo" in str(tool_calls[0]["function"]["arguments"])


if __name__ == "__main__":
    test_live_qwen_tool_call()
    print("\nSUCCESS: Live tool-calling verified on qwen2.5:7b-instruct!")
