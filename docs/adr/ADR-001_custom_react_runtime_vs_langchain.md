# ADR-001: Custom ReAct Runtime vs. LangChain / CrewAI

## Status
**Accepted** (2026-08)

## Context
When architecting an autonomous desktop agent, developers typically default to existing third-party orchestration frameworks such as LangChain, CrewAI, or AutoGen. 

However, Project Aether has strict operational requirements:
1. **Long-Running Local Daemon**: The agent runs continuously as a workstation background process with scheduled morning briefings and email triage without memory leaks.
2. **Local 7B/14B Parameter Models**: When running against local quantizations via Ollama (e.g., Qwen 2.5 7B), models exhibit specific failure modes: hallucinating extra parameters, emitting non-standard JSON, or omitting snake_case underscores in tool names.
3. **Deterministic Low-Latency Tool Dispatch**: Overhead from multi-layered framework abstractions directly adds latency to voice interactions and streaming UI updates.

## Decision
We decided to build a custom, zero-bloat ReAct (Reasoning + Acting) execution runtime in native Python ([`src/agent/loop.py`](file:///C:/Users/jrrya/Projects/aether/src/agent/loop.py)) utilizing standard library primitives (`inspect`, `json`, `re`, `shlex`) and lightweight async HTTP (`httpx`).

Key architectural components implemented:
- **Dynamic Argument Pruning via Signature Reflection**: Tool invocations inspect the target function signature (`inspect.signature`) at runtime, stripping hallucinated keyword arguments before execution without throwing exceptions.
- **Fuzzy Tool Resolution**: Maps malformed tool names (e.g. `fileslistdirectory` -> `files_list_directory`) to registered MCP tools.
- **Circuit Breakers**: Detects consecutive repeated tool errors and aborts execution before entering infinite doom loops.
- **Stream Event Yields**: Emits granular Server-Sent Events (`thought`, `tool_call`, `observation`, `token`) directly to the web client.

## Consequences
### Positive
- **Zero Framework Dependency Bloat**: Eliminates ~50 transitive dependencies and rapid breaking API changes.
- **Sub-50ms Orchestration Overhead**: Tool dispatch is instantaneous without intermediate abstraction layers.
- **Tailored Resilience**: Directly handles the exact token generation quirks of open-weight 7B models.
- **Auditability**: 100% of the execution loop is visible, debuggable, and testable via standard unit tests.

### Negative
- We must maintain the tool-calling loop, JSON extraction fallback, and multi-step state machine internally rather than relying on external library releases.

## Alternatives Considered
- **LangChain / LangGraph**: Evaluated initially. Rejected due to heavy dependency footprints, complex state abstractions that leak memory over long daemon runtimes, and difficulty injecting runtime signature reflection.
- **CrewAI**: Designed around multi-agent conversational roleplay, which introduces high token overhead and latency ill-suited for local 8 GB VRAM hardware.
