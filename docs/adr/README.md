# Project Aether: Architecture Decision Records (ADRs)

This directory documents the significant architectural decisions made during the design, development, and evolution of Project Aether.

Each record follows the standard Michael Nygard ADR format:
- **Status**: Proposed, Accepted, Superceded, or Deprecated.
- **Context**: The engineering problem, constraints, and forces at play.
- **Decision**: The architectural choice made and technical rationale.
- **Consequences**: Positive and negative trade-offs of the choice.
- **Alternatives Considered**: Other tools, frameworks, or patterns evaluated and why they were rejected.

---

## Index of Records

| ADR | Title | Status | Date | Primary Drivers |
| :--- | :--- | :--- | :--- | :--- |
| [ADR-001](file:///C:/Users/jrrya/Projects/aether/docs/adr/ADR-001_custom_react_runtime_vs_langchain.md) | Custom ReAct Runtime vs. LangChain / CrewAI | **Accepted** | 2026-08 | Reliability, zero bloat, signature reflection, memory stability |
| [ADR-002](file:///C:/Users/jrrya/Projects/aether/docs/adr/ADR-002_dynamic_tool_masking_vs_monolithic_catalogs.md) | Dynamic Intent Tool Masking vs. Monolithic Catalogs | **Accepted** | 2026-08 | Token efficiency, attention density, hallucination prevention |
| [ADR-003](file:///C:/Users/jrrya/Projects/aether/docs/adr/ADR-003_mcp_stdio_jsonrpc_vs_inprocess_tools.md) | Model Context Protocol (MCP) stdio vs. In-Process Tools | **Accepted** | 2026-08 | Process isolation, fault containment, industry standard |
| [ADR-004](file:///C:/Users/jrrya/Projects/aether/docs/adr/ADR-004_neural_edge_tts_and_whisper_spotter.md) | Neural Edge-TTS & Whisper Spotter vs. SAPI & openWakeWord | **Accepted** | 2026-09 | Natural speech quality, custom wake word flexibility, instant barge-in |
| [ADR-005](file:///C:/Users/jrrya/Projects/aether/docs/adr/ADR-005_anti_ai_slop_design_system.md) | Anti-AI-Slop Zinc + Sky Blue UI vs. Glassmorphic Glows | **Accepted** | 2026-09 | High information density, GPU performance, accessibility, zero slop |
| [ADR-006](file:///C:/Users/jrrya/Projects/aether/docs/adr/ADR-006_ast_command_sandbox_and_hitl_gates.md) | AST Command Sandboxing & HITL Safety Gates | **Accepted** | 2026-08 | Defense against indirect prompt injection and destructive shell commands |
| [ADR-007](file:///C:/Users/jrrya/Projects/aether/docs/adr/ADR-007_offline_storage_sqlite_wal_and_markdown_vault.md) | Embedded SQLite WAL & Markdown Vault vs. Cloud Databases | **Accepted** | 2026-08 | Offline-first privacy, ACID transactions, human-readable data ownership |
