# Project Aether: Offline-First Desktop Automation Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Protocol: MCP](https://img.shields.io/badge/protocol-MCP-orange.svg)](https://modelcontextprotocol.io/)
[![Runtime: Ollama/vLLM](https://img.shields.io/badge/runtime-Ollama%20%7C%20vLLM-purple.svg)](https://ollama.ai/)

**Aether** is an offline-first, privacy-respecting local desktop automation agent. It pairs locally hosted Large Language Models (such as Qwen 2.5 14B or Llama 3.1 8B) with operating system automations using Anthropic's **Model Context Protocol (MCP)**. 

Aether operates entirely on consumer hardware without leaking user data, personal schedules, emails, or notes to third-party cloud services.

---

## Key Highlights

- **100% Local Inference**: Runs against local model servers like [Ollama](https://ollama.ai) or [vLLM](https://github.com/vllm-project/vllm).
- **Photorealistic Image Generation**: Local txt2img diffusion engine powered by **Juggernaut XL v9** (6.61 GB SDXL) on ComfyUI with on-demand auto-wake and a 10-minute idle auto-sleep watchdog to free VRAM.
- **Autonomous Coding & Antigravity Mode**: Built-in code intelligence with directory tree inspection, targeted snippet patching, and sandboxed terminal command execution.
- **Extensible via MCP**: Calendar, email, and notes operations are isolated standalone MCP stdio servers. New capabilities can be added as standard MCP servers.
- **Strict Human-in-the-Loop (HITL) Safety Intercept**: Any mutating action (sending drafts, booking calendar slots, modifying/deleting notes) requires explicit terminal or UI confirmation before execution.
- **Markdown Vault Integration**: Native support for Obsidian, Logseq, or raw Markdown vaults with daily notes, todo checkboxes (`- [ ]`), and tag searching.
- **Robust Threat Defense**: Demarcation tags (`<untrusted_content>`) isolate incoming emails and external data to neutralize indirect prompt injection attacks.

---

## Quick Start & Web Dashboard

### One-Click Portal Launch
- **Windows Explorer**: Double-click [start_portal.bat](file:///c:/Users/jrrya/Projects/aether/start_portal.bat) in the project root.
- **PowerShell**: Run `./start_portal.ps1` or `.venv\Scripts\python main.py --portal --open`.

The launcher automatically:
1. Verifies the local virtual environment.
2. Checks that Ollama is running (and starts `ollama serve` in the background if needed).
3. Launches the web dashboard on `http://127.0.0.1:8000`.
4. Opens your default web browser to the dashboard.

### Interactive CLI Mode
```bash
.venv\Scripts\python main.py
```

---

## Architecture Overview

```mermaid
flowchart TD
    User([User / CLI / Raycast]) -->|Prompt| Core[Aether Orchestration Core]
    
    subgraph Core [Aether Orchestration Core (Python)]
        Context[Context Manager & Token Budgeter]
        Loop[ReAct Tool-Calling Loop]
        HITL{Safety Guard / HITL Interceptor}
        MCPClient[MCP Client Manager]
        
        Context --> Loop
        Loop -->|Mutating Action?| HITL
        HITL -->|Approved| MCPClient
        HITL -.->|Rejected| Loop
    end
    
    Loop <-->|OpenAI-compatible Chat API| LLM[Local Model Server\nOllama / vLLM\ne.g. Qwen 2.5 14B]
    
    MCPClient <-->|stdio JSON-RPC| S_Cal[Calendar Server\nGoogle Calendar / CalDAV]
    MCPClient <-->|stdio JSON-RPC| S_Mail[Mail Server\nIMAP / Drafts]
    MCPClient <-->|stdio JSON-RPC| S_Notes[Notes Server\nMarkdown Vault / SQLite]
    MCPClient <-->|stdio JSON-RPC| S_Custom[Custom MCP Servers\nBrowser / Audio / Shell]
    
    S_Cal <--> CalAPI[(Calendar Provider)]
    S_Mail <--> MailAPI[(Mail Server)]
    S_Notes <--> Vault[(Local Markdown Vault\ndata/vault)]
```

---

## System Requirements & Performance Targets

| Metric | Target Specification |
| :--- | :--- |
| **Inference Runtime** | Ollama or vLLM |
| **Recommended Model** | `qwen2.5:14b-instruct` (10–12 GB VRAM) or `llama3.1:8b-instruct` (<6 GB VRAM) |
| **Host Memory** | Orchestrator RAM < 500 MB |
| **Latency Target** | 1.5–3.0 seconds end-to-end tool dispatch on modern consumer hardware |
| **Platforms** | Linux, macOS, Windows (WSL2 / native Python 3.11+) |

---

## Directory Layout

```text
aether/
├── config/
│   ├── config.yaml              # Runtime configuration, models, polling intervals
│   └── mcp_servers.json         # Executable paths and environments for MCP servers
├── docs/                        # Complete technical specification suite
│   ├── 01_architecture_and_threat_model.md
│   ├── 02_mcp_server_contracts.md
│   ├── 03_orchestrator_and_agent_loop.md
│   ├── 04_data_models_and_storage.md
│   ├── 05_configuration_and_environment.md
│   └── 06_testing_and_verification_plan.md
├── src/
│   ├── agent/
│   │   ├── loop.py              # Main ReAct / tool execution loop
│   │   ├── prompts.py           # System prompts, temporal grounding, guidelines
│   │   └── guardrails.py        # Safety gate requiring approval for write operations
│   ├── client/
│   │   └── ollama_client.py     # Client interface for local LLM inference
│   ├── mcp_bridge/
│   │   └── manager.py           # Process manager and stdio transport for MCP tools
│   ├── servers/                 # Built-in FastMCP Servers
│   │   ├── calendar_server.py   # Calendar manager (CalDAV / Google API)
│   │   ├── mail_server.py       # IMAP unread triage & draft stager
│   │   └── notes_server.py      # Markdown vault parser & task tracker
│   └── main.py                  # CLI entry point (interactive chat & scheduled daemon)
├── data/
│   ├── aether.db                # SQLite database for audit logs, cache & vector embeddings
│   └── vault/                   # Local Markdown notes, daily notes & tasks
├── pyproject.toml
└── README.md
```

---

## Technical Specifications

Read the comprehensive technical design documents in the [`docs/`](./docs) directory:

1. [**01. Architecture & Threat Model**](./docs/01_architecture_and_threat_model.md): Detailed subsystem interactions, indirect prompt injection defense, and security perimeter.
2. [**02. MCP Server Contracts & Schemas**](./docs/02_mcp_server_contracts.md): Complete JSON schemas, arguments, return payloads, and error codes for built-in MCP servers.
3. [**03. Orchestrator & Agent Loop**](./docs/03_orchestrator_and_agent_loop.md): ReAct execution cycle, temporal grounding, context budgeting, and HITL gate mechanics.
4. [**04. Data Models & Storage**](./docs/04_data_models_and_storage.md): SQLite relational schema (`aether.db`), vector indexing strategy, and Markdown vault structure.
5. [**05. Configuration & Environment**](./docs/05_configuration_and_environment.md): Structure of `config.yaml`, `mcp_servers.json`, credential separation, and environment variables.
6. [**06. Testing & Verification Plan**](./docs/06_testing_and_verification_plan.md): Unit test harness, mock stdio server execution, and safety gate regression suites.

---

## Roadmap

- [x] **Phase 0: Specifications & Documentation**: Formal schemas, threat models, and interface contracts.
- [x] **Phase 1: Local LLM & Tool Sandbox**: Agent loop, mock MCP execution, Ollama integration.
- [x] **Phase 2: Notes & Task Engine**: FastMCP notes server, task appending, keyword search in vault.
- [x] **Phase 3: Calendar & Mail Integrations**: Google Calendar / CalDAV reader & writer, IMAP unread triage, draft staging.
- [x] **Phase 4: Daemon & Background Briefings**: Daily 07:30 automated briefings, summarizing unread emails and upcoming agenda into daily notes.
- [x] **Phase 5: Autonomous Code Engineering & Antigravity Mode**: Workspace exploration, targeted snippet patch engine, and sandboxed terminal command runner.
- [x] **Phase 6: Local Diffusion Image Subsystem**: ComfyUI integration, on-demand auto-wake and auto-sleep lifecycle manager, upgraded to **Juggernaut XL v9** photorealistic diffusion.
