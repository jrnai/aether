"""Bridge service for codebase-memory-mcp knowledge graph.

Provides local AST symbol search, caller/callee reference tracing, source snippet
retrieval, and architecture topology summaries for Aether's coding agent.
"""

import json
import logging
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("aether.graph_bridge")

# Default search paths for codebase-memory-mcp executable
DEFAULT_BINARY_PATHS = [
    Path.home() / ".local" / "bin" / "codebase-memory-mcp.exe",
    Path.home() / ".local" / "bin" / "codebase-memory-mcp",
]


class StdioJsonRpcClient:
    """Resilient stdio JSON-RPC 2.0 client for local MCP binary services."""

    def __init__(self, command: list[str], cwd: str | None = None) -> None:
        self.command = command
        self.cwd = cwd
        self.proc: subprocess.Popen[str] | None = None
        self.req_id = 0
        self.pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self.lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._is_running = False

    def start(self) -> None:
        """Spawn the process and background reader threads."""
        if self._is_running:
            return

        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            text=True,
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._is_running = True

        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        if not self.proc or not self.proc.stderr:
            return
        while self._is_running:
            line = self.proc.stderr.readline()
            if not line:
                break

    def _read_loop(self) -> None:
        if not self.proc or not self.proc.stdout:
            return
        while self._is_running:
            line = self.proc.stdout.readline()
            if not line:
                break
            clean_line = line.strip()
            if not clean_line:
                continue
            try:
                data = json.loads(clean_line)
                msg_id = data.get("id")
                if msg_id is not None and msg_id in self.pending:
                    fut_q = self.pending.pop(msg_id)
                    fut_q.put(data)
            except Exception as e:
                logger.debug("Error parsing JSON-RPC line: %s", e)

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
        """Send JSON-RPC 2.0 request and wait for the response."""
        if not self._is_running or not self.proc or not self.proc.stdin:
            self.start()

        with self.lock:
            self.req_id += 1
            cid = self.req_id

        q: queue.Queue[dict[str, Any]] = queue.Queue()
        self.pending[cid] = q

        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": cid, "method": method}
        if params is not None:
            msg["params"] = params

        payload = json.dumps(msg) + "\n"
        try:
            assert self.proc is not None and self.proc.stdin is not None
            self.proc.stdin.write(payload)
            self.proc.stdin.flush()
            return q.get(timeout=timeout)
        except queue.Empty:
            self.pending.pop(cid, None)
            raise TimeoutError(f"JSON-RPC call '{method}' timed out after {timeout}s")
        except Exception as e:
            self.pending.pop(cid, None)
            raise RuntimeError(f"JSON-RPC communication error: {e}") from e

    def close(self) -> None:
        """Terminate the process."""
        self._is_running = False
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2.0)
            except Exception:
                pass
            self.proc = None


class CodebaseGraphBridge:
    """Manages connection to codebase-memory-mcp and provides high-level graph queries."""

    def __init__(self, binary_path: str | Path | None = None, workspace_dir: str | Path | None = None) -> None:
        self.binary_path = self._resolve_binary(binary_path)
        self.workspace_dir = Path(workspace_dir).resolve() if workspace_dir else Path.cwd().resolve()
        self.project_name = self.workspace_dir.name
        self.client: StdioJsonRpcClient | None = None
        self._initialized = False

    def _resolve_binary(self, custom_path: str | Path | None) -> Path | None:
        if custom_path:
            p = Path(custom_path)
            if p.exists():
                return p

        # Check default paths
        for candidate in DEFAULT_BINARY_PATHS:
            if candidate.exists():
                return candidate

        # Check PATH
        which_path = shutil.which("codebase-memory-mcp")
        if which_path:
            return Path(which_path)

        return None

    def is_available(self) -> bool:
        """Return True if the binary is discovered on the system."""
        return self.binary_path is not None and self.binary_path.exists()

    def ensure_connected(self) -> None:
        """Ensure the MCP client is started and initialized."""
        if self._initialized and self.client and self.client._is_running:
            return

        if not self.is_available():
            raise FileNotFoundError("codebase-memory-mcp executable not found on system.")

        assert self.binary_path is not None
        self.client = StdioJsonRpcClient([str(self.binary_path)], cwd=str(self.workspace_dir))
        self.client.start()

        # Initialize protocol
        init_res = self.client.call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "aether-graph-bridge", "version": "1.0"},
            },
            timeout=10.0,
        )
        if "error" in init_res:
            raise RuntimeError(f"Failed to initialize codebase-memory-mcp: {init_res['error']}")

        self._initialized = True
        logger.info("Connected to codebase-memory-mcp for project '%s'", self.project_name)

    def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Invoke a tool on codebase-memory-mcp and return formatted text."""
        self.ensure_connected()
        assert self.client is not None

        # Auto-inject project name if not specified
        if "project" not in arguments or not arguments["project"]:
            arguments["project"] = self.project_name

        res = self.client.call("tools/call", {"name": tool_name, "arguments": arguments}, timeout=20.0)

        result_obj = res.get("result", {})
        if "content" in result_obj:
            content = result_obj["content"]
            texts = [c.get("text", "") for c in content if isinstance(c, dict)]
            return "\n".join(texts)
        if "error" in res:
            return json.dumps(res["error"])
        return json.dumps(result_obj)

    def search_symbols(self, name_pattern: str, file_pattern: str = "") -> str:
        """Search functions, classes, methods, routes, and variables by regex pattern."""
        try:
            args: dict[str, Any] = {"name_pattern": name_pattern}
            if file_pattern:
                args["file_pattern"] = file_pattern
            return self._call_tool("search_graph", args)
        except Exception as e:
            return json.dumps({"error": f"Symbol search failed: {e}"})

    def trace_references(self, function_name: str, direction: str = "inbound") -> str:
        """Trace callers (inbound) or callees (outbound) for a function or method."""
        try:
            args: dict[str, Any] = {
                "function_name": function_name,
                "direction": direction if direction in ("inbound", "outbound") else "inbound",
            }
            return self._call_tool("trace_path", args)
        except Exception as e:
            return json.dumps({"error": f"Reference trace failed: {e}"})

    def get_code_snippet(self, qualified_name: str) -> str:
        """Retrieve AST code snippet and line boundaries by exact qualified name."""
        try:
            args: dict[str, Any] = {"qualified_name": qualified_name}
            return self._call_tool("get_code_snippet", args)
        except Exception as e:
            return json.dumps({"error": f"Snippet retrieval failed: {e}"})

    def get_architecture(self) -> str:
        """Retrieve high-level architectural statistics and node summaries."""
        try:
            return self._call_tool("get_architecture", {})
        except Exception as e:
            return json.dumps({"error": f"Architecture query failed: {e}"})

    def get_status(self) -> dict[str, Any]:
        """Return readiness and connectivity status."""
        available = self.is_available()
        return {
            "available": available,
            "binary_path": str(self.binary_path) if self.binary_path else None,
            "project_name": self.project_name,
            "connected": self._initialized and self.client is not None and self.client._is_running,
        }

    def close(self) -> None:
        """Shut down the client process."""
        if self.client:
            self.client.close()
            self.client = None
        self._initialized = False
