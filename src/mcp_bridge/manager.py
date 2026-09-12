"""MCP Bridge Manager: supervises stdio MCP servers, discovers tools, and binds to AgentLoop."""
import asyncio
import json
import logging
import os
import sys
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.agent.loop import AgentLoop

logger = logging.getLogger("aether.mcp_bridge")

# Explicit mutation keywords for automatic safety classification
MUTATING_KEYWORDS = ("add", "append", "create", "delete", "stage", "write", "modify", "remove", "update", "send")


class _ServerWorker:
    """Worker handling the stdio session for a single MCP server."""

    def __init__(self, name: str, params: StdioServerParameters) -> None:
        self.name = name
        self.params = params
        self.queue: asyncio.Queue[tuple[str, dict[str, Any], Future[Any]] | None] = asyncio.Queue()
        self.tools: list[Any] = []

    async def run(self, ready_fut: Future[list[Any]]) -> None:
        try:
            async with stdio_client(self.params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_res = await session.list_tools()
                    self.tools = tools_res.tools
                    ready_fut.set_result(self.tools)

                    while True:
                        req = await self.queue.get()
                        if req is None:
                            break

                        tool_name, args, res_fut = req
                        try:
                            result = await session.call_tool(tool_name, args)
                            # Flatten text content
                            texts = []
                            for c in result.content:
                                if hasattr(c, "text"):
                                    texts.append(c.text)
                                else:
                                    texts.append(str(c))
                            out = "\n".join(texts)
                            res_fut.set_result(out)
                        except Exception as ex:
                            res_fut.set_exception(ex)
        except Exception as e:
            if not ready_fut.done():
                ready_fut.set_exception(e)
            logger.error("Error in server worker '%s': %s", self.name, e)


class MCPBridgeManager:
    """Manages active stdio MCP servers and bridges their tools to the Aether AgentLoop."""

    def __init__(self, config_path: str = "config/mcp_servers.json") -> None:
        self.config_path = Path(config_path)
        self.workers: dict[str, _ServerWorker] = {}
        self.tool_to_server: dict[str, str] = {}
        self.tools_metadata: dict[str, Any] = {}

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._is_running = False

    def _ensure_event_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or not self._is_running:
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
            self._thread.start()
            self._is_running = True
        return self._loop

    def load_config(self) -> dict[str, Any]:
        """Load MCP server configurations from file or fallback to example blueprint."""
        target_path = self.config_path
        if not target_path.exists():
            example_path = target_path.with_name("mcp_servers.example.json")
            if example_path.exists():
                target_path = example_path

        if not target_path.exists():
            logger.warning("No MCP configuration found at %s. Using default notes server.", self.config_path)
            return {
                "mcpServers": {
                    "notes": {
                        "command": sys.executable,
                        "args": ["src/servers/notes_server.py"],
                        "env": {"AETHER_VAULT_DIR": "./data/vault"},
                    }
                }
            }

        with open(target_path, encoding="utf-8") as f:
            data = json.load(f)
            return data.get("mcpServers", {})

    def start(self) -> None:
        """Start all configured MCP servers and discover their tools."""
        loop = self._ensure_event_loop()
        server_configs = self.load_config()

        for srv_name, srv_conf in server_configs.items():
            cmd = srv_conf.get("command", "python")
            # Ensure we use the current Python interpreter if 'python' is requested
            if cmd in ("python", "python3"):
                cmd = sys.executable

            args = srv_conf.get("args", [])
            raw_env = srv_conf.get("env", {})
            env = {**os.environ, **raw_env}

            params = StdioServerParameters(command=cmd, args=args, env=env)
            worker = _ServerWorker(srv_name, params)
            ready_fut: Future[list[Any]] = Future()

            # Schedule worker on background loop
            task = asyncio.run_coroutine_threadsafe(worker.run(ready_fut), loop)
            self._tasks.append(task)

            try:
                tools = ready_fut.result(timeout=15.0)
                self.workers[srv_name] = worker
                for tool in tools:
                    self.tool_to_server[tool.name] = srv_name
                    self.tools_metadata[tool.name] = tool
                logger.info("Server '%s' started with tools: %s", srv_name, [t.name for t in tools])
            except Exception as e:
                logger.error("Failed to start MCP server '%s': %s", srv_name, e)

    def call_tool(self, tool_name: str, arguments: dict[str, Any], timeout: float = 30.0) -> str:
        """Execute a tool on the designated MCP server process."""
        if tool_name not in self.tool_to_server:
            raise KeyError(f"Tool '{tool_name}' is not registered with any running MCP server.")

        srv_name = self.tool_to_server[tool_name]
        worker = self.workers[srv_name]

        if not self._loop or not self._is_running:
            raise RuntimeError("MCPBridgeManager is not running.")

        res_fut: Future[str] = Future()
        asyncio.run_coroutine_threadsafe(worker.queue.put((tool_name, arguments, res_fut)), self._loop)
        return res_fut.result(timeout=timeout)

    def register_all_tools(self, loop: AgentLoop) -> None:
        """Register all discovered MCP tools directly into the AgentLoop."""
        for tool_name, tool_obj in self.tools_metadata.items():
            # Build parameter schema
            params_schema: dict[str, Any] = {}
            if hasattr(tool_obj, "input_schema") and tool_obj.input_schema:
                params_schema = tool_obj.input_schema
            elif hasattr(tool_obj, "inputSchema") and tool_obj.inputSchema:
                params_schema = tool_obj.inputSchema
            elif hasattr(tool_obj, "parameters") and tool_obj.parameters:
                params_schema = tool_obj.parameters

            # Determine safety classification
            is_safe = not any(kw in tool_name.lower() for kw in MUTATING_KEYWORDS)

            description = getattr(tool_obj, "description", "") or f"Tool {tool_name}"

            # Bind callable dispatching through manager
            def make_dispatcher(name: str):
                return lambda **kwargs: self.call_tool(name, kwargs)

            loop.register_tool(
                name=tool_name,
                description=description,
                parameters=params_schema,
                func=make_dispatcher(tool_name),
                safe=is_safe,
            )

    def stop(self) -> None:
        """Gracefully terminate all running MCP server processes."""
        if not self._is_running or not self._loop:
            return

        for worker in self.workers.values():
            asyncio.run_coroutine_threadsafe(worker.queue.put(None), self._loop)

        # Wait briefly for tasks to exit
        for task in self._tasks:
            try:
                task.result(timeout=2.0)
            except Exception:
                pass

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        self._is_running = False
        self.workers.clear()
        self.tool_to_server.clear()
        self.tools_metadata.clear()
        logger.info("MCPBridgeManager stopped.")

    def __enter__(self) -> "MCPBridgeManager":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
