# ADR-003: Model Context Protocol (MCP) stdio JSON-RPC vs. In-Process Tools

## Status
**Accepted** (2026-08)

## Context
A desktop agent needs to interface with multiple disparate local and networked subsystems: CalDAV/Google Calendar, IMAP/SMTP mail clients, local filesystem workspaces, AST symbol graphs, and browser search.

Direct in-process execution (importing all libraries directly into the orchestrator process) presents significant reliability risks:
1. A segmentation fault or memory leak in a third-party C-extension (e.g. cryptographic libraries, image decoders) crashes the entire agent.
2. Blocking network I/O in legacy libraries can hang the asynchronous event loop.
3. No clean isolation boundaries exist between the agent core and OS-level operations.

## Decision
We adopted Anthropic's **Model Context Protocol (MCP)** specification over standard I/O (`stdio` JSON-RPC 2.0) for tool isolation ([`src/mcp_bridge/manager.py`](file:///C:/Users/jrrya/Projects/aether/src/mcp_bridge/manager.py)):
- Tools are executed as standalone subprocesses communicating via asynchronous JSON-RPC 2.0.
- A dedicated connection manager (`MCPBridgeManager`) handles process spawning, lifecycle monitoring, stdout/stderr draining, and timeout supervision.
- Subprocesses that freeze or exceed execution timeouts (e.g. hung IMAP connections) can be safely terminated and restarted without disrupting the main orchestrator.

## Consequences
### Positive
- **Fault Containment**: Crashes or unhandled exceptions in tool execution do not compromise orchestrator stability.
- **Ecosystem Compatibility**: Aether can consume third-party MCP servers (e.g. `codebase-memory-mcp`, SQLite MCP, GitHub MCP) with zero code rewrites.
- **Process Boundaries for Security**: Operating system privileges can be dropped or sandboxed per MCP subprocess.

### Negative
- IPC overhead of JSON serialization and stdio pipe transfer adds 1–3ms per call (negligible compared to LLM inference latency).
- Managing multiple subprocess lifecycles requires robust process cleanup on application shutdown.

## Alternatives Considered
- **Direct In-Memory Python Functions**: Initially used in early prototypes. Rejected after an IMAP network timeout blocked the main async thread.
- **HTTP REST Microservices**: Spawning local HTTP servers for every tool suite adds port collisions, TCP overhead, and local firewall alert complications on Windows.
