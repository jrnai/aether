"""Sandbox demo script to verify LLM tool-calling and the HITL safety intercept."""
from datetime import datetime
from src.agent.guardrails import SafetyGuard
from src.agent.loop import AgentLoop
from src.client.ollama_client import OllamaClient


def get_system_status() -> dict:
    """Safe read-only tool returning system health and local time."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "battery": "100%",
        "load": "0.15",
    }


def write_test_entry(filename: str, content: str) -> dict:
    """Mutating write tool that creates or modifies a test file (requires user confirmation)."""
    return {
        "status": "success",
        "file": filename,
        "bytes_written": len(content),
        "message": f"Successfully wrote '{content}' to {filename}.",
    }


def run_demo() -> None:
    print("=" * 60)
    print("Project Aether: Phase 1 Sandbox Tool-Calling Demo")
    print("=" * 60)

    client = OllamaClient(default_model="qwen2.5:14b-instruct")
    if not client.is_connected():
        print("\n[NOTE] Local Ollama server is not running on http://127.0.0.1:11434.")
        print("To run with live models: start Ollama via `ollama serve`.")
        print("Running unit tests with Mock clients will verify all state machine behaviors.\n")
        return

    print("Connected to Ollama! Available models:", client.list_models())

    guard = SafetyGuard()
    loop = AgentLoop(client=client, guard=guard)

    # Register safe tool
    loop.register_tool(
        name="get_system_status",
        description="Get current system health, battery, and timestamp.",
        parameters={"type": "object", "properties": {}},
        func=get_system_status,
        safe=True,
    )

    # Register mutating tool
    loop.register_tool(
        name="write_test_entry",
        description="Write a test entry into a specified file.",
        parameters={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Target filename"},
                "content": {"type": "string", "description": "Text content to write"},
            },
            "required": ["filename", "content"],
        },
        func=write_test_entry,
        safe=False,
    )

    print("\nRegistered tools:")
    print(" - get_system_status (safe=True)")
    print(" - write_test_entry (safe=False, requires HITL approval)")
    print("\nStarting interactive test session. Type 'exit' to quit.")

    while True:
        try:
            query = input("\nUser > ").strip()
            if not query or query.lower() in ("exit", "quit"):
                break
            response = loop.run_turn(query)
            print(f"\nAether > {response}")
        except (KeyboardInterrupt, EOFError):
            break


if __name__ == "__main__":
    run_demo()
