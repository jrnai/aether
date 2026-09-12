"""End-to-end integration test: local Qwen 2.5 LLM + MCP stdio Bridge + Markdown Vault."""
import json
from pathlib import Path
import pytest
from src.agent.guardrails import SafetyGuard
from src.agent.loop import AgentLoop
from src.client.ollama_client import OllamaClient
from src.mcp_bridge.manager import MCPBridgeManager


def test_live_agent_reads_vault_note(tmp_path: Path) -> None:
    client = OllamaClient(default_model="qwen2.5:7b-instruct")
    if not client.is_connected():
        pytest.skip("Local Ollama is not reachable.")

    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "Inbox.md").write_text(
        "# Inbox\n\nTasks captured on the fly:\n\n- [ ] Order USB cables #tasks\n",
        encoding="utf-8",
    )

    cfg_data = {
        "mcpServers": {
            "notes": {
                "command": "python",
                "args": ["src/servers/notes_server.py"],
                "env": {"AETHER_VAULT_DIR": str(vault_dir)},
            }
        }
    }
    cfg_file = tmp_path / "mcp_notes.json"
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")

    guard = SafetyGuard()
    loop = AgentLoop(model="qwen2.5:7b-instruct", client=client, guard=guard)
    manager = MCPBridgeManager(config_path=str(cfg_file))

    with manager:
        manager.register_all_tools(loop)

        # Ask to read the Inbox project note
        response = loop.run_turn("Read my Inbox project note and list the tasks written in it.")
        print("\nAgent response:", response)

        assert any(keyword in response.lower() for keyword in ["usb", "cables", "tasks", "inbox"])


def test_live_agent_adds_todo_with_hitl_approval(tmp_path: Path) -> None:
    client = OllamaClient(default_model="qwen2.5:7b-instruct")
    if not client.is_connected():
        pytest.skip("Local Ollama is not reachable.")

    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "Inbox.md").write_text(
        "# Inbox\n\nTasks captured on the fly:\n\n",
        encoding="utf-8",
    )

    cfg_data = {
        "mcpServers": {
            "notes": {
                "command": "python",
                "args": ["src/servers/notes_server.py"],
                "env": {"AETHER_VAULT_DIR": str(vault_dir)},
            }
        }
    }
    cfg_file = tmp_path / "mcp_notes_add.json"
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")

    approval_log = []

    def auto_approve(tool_name: str, args: dict) -> bool:
        approval_log.append((tool_name, args))
        return True

    guard = SafetyGuard(confirmation_callback=auto_approve)
    loop = AgentLoop(model="qwen2.5:7b-instruct", client=client, guard=guard)
    manager = MCPBridgeManager(config_path=str(cfg_file))

    with manager:
        manager.register_all_tools(loop)

        # Prompt that triggers mutating action
        response = loop.run_turn("Add a todo item 'Review security guidelines' to my Inbox")
        print("\nAgent mutation response:", response)

        # Verify HITL gate was intercepted
        assert len(approval_log) > 0
        assert approval_log[0][0] == "add_todo_item"
        assert "security" in str(approval_log[0][1]).lower()
