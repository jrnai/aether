"""Integration tests for the stdio MCPBridgeManager and notes_server."""
import pytest
from src.agent.guardrails import SafetyGuard
from src.agent.loop import AgentLoop
from src.mcp_bridge.manager import MCPBridgeManager


def test_mcp_bridge_lifecycle_and_tool_call() -> None:
    # Use example config which targets notes_server
    manager = MCPBridgeManager(config_path="config/mcp_servers.example.json")

    with manager:
        # Verify tool discovery
        assert "notes" in manager.workers
        tools = list(manager.tool_to_server.keys())
        assert "search_notes" in tools
        assert "read_project_notes" in tools
        assert "add_todo_item" in tools

        # Test calling a safe tool via stdio JSON-RPC
        output = manager.call_tool("read_project_notes", {"project": "Aether"})
        assert "Project Aether" in output
        assert "Architecture Decisions" in output


def test_mcp_bridge_registers_into_agent_loop() -> None:
    manager = MCPBridgeManager(config_path="config/mcp_servers.example.json")
    guard = SafetyGuard()
    loop = AgentLoop(guard=guard)

    with manager:
        manager.register_all_tools(loop)

        # Check that tools got registered into AgentLoop
        registered_names = [t["function"]["name"] for t in loop.tools_schema]
        assert "search_notes" in registered_names
        assert "add_todo_item" in registered_names

        # Verify safety flags
        assert guard.is_safe("search_notes") is True
        assert guard.is_safe("read_project_notes") is True
        assert guard.is_safe("add_todo_item") is False  # Mutating!
        assert guard.is_safe("append_note") is False    # Mutating!
