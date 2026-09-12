"""Unit tests for AST CodebaseGraphBridge and coding agent tool registration."""

import json
from unittest.mock import MagicMock
import pytest
from src.mcp_bridge.graph_bridge import CodebaseGraphBridge
from src.web.server import get_coder_agent_loop, get_graph_bridge


def test_graph_bridge_availability() -> None:
    bridge = CodebaseGraphBridge()
    status = bridge.get_status()
    assert "available" in status
    assert "project_name" in status
    assert status["project_name"] == "aether"


def test_graph_bridge_queries_if_available() -> None:
    bridge = CodebaseGraphBridge()
    if not bridge.is_available():
        pytest.skip("codebase-memory-mcp binary not present on system")

    # 1. search_symbols
    sym_res = bridge.search_symbols("AgentLoop")
    assert "AgentLoop" in sym_res

    # 2. trace_references
    trace_res = bridge.trace_references("run_turn")
    assert "run_turn" in trace_res

    # 3. get_architecture
    arch_res = bridge.get_architecture()
    assert "total_nodes" in arch_res or "project" in arch_res

    # 4. get_code_snippet
    snippet_res = bridge.get_code_snippet("aether.src.agent.loop.AgentLoop.run_turn")
    assert "run_turn" in snippet_res
    assert "loop.py" in snippet_res


def test_coder_agent_loop_has_graph_tools() -> None:
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    loop = get_coder_agent_loop(client=mock_client, reset=True)
    tool_names = [t["function"]["name"] for t in loop.tools_schema]

    assert "graph_search_symbols" in tool_names
    assert "graph_trace_references" in tool_names
    assert "graph_get_code_snippet" in tool_names
    assert "graph_get_architecture" in tool_names

    # Check that graph tools are marked safe
    assert loop.guard.is_safe("graph_search_symbols") is True
    assert loop.guard.is_safe("graph_trace_references") is True
    assert loop.guard.is_safe("graph_get_code_snippet") is True
    assert loop.guard.is_safe("graph_get_architecture") is True
