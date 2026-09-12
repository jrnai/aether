# Aether Specification 05: Configuration & Environment Specification

## 1. Configuration Architecture

Aether uses a layered configuration hierarchy with clear precedence:

```
    Precedence Order (Highest to Lowest):
    1. Command-Line Arguments (--model, --vault-dir)
    2. Environment Variables (AETHER_*, IMAP_*, CALENDAR_*)
    3. YAML Configuration (config/config.yaml)
    4. Built-in Internal Defaults
```

All persistent configuration files reside in `config/`. Secrets and access credentials are kept strictly isolated from LLM prompts and configuration files committed to source control.

---

## 2. Core Configuration Schema (`config/config.yaml`)

```yaml
# ==============================================================================
# Project Aether Core Configuration
# ==============================================================================

version: "1.0"

# LLM Inference Server Configuration
llm:
  provider: "ollama"                         # "ollama" or "vllm"
  base_url: "http://localhost:11434"
  model: "qwen2.5:14b-instruct"              # Recommended: qwen2.5:14b-instruct or llama3.1:8b-instruct
  temperature: 0.1                           # Low temperature for deterministic tool calling
  context_window_tokens: 8192                # Hard context ceiling
  max_turn_steps: 8                          # Maximum ReAct loops before halting

# Local Storage Paths
storage:
  database_path: "./data/aether.db"
  vault_path: "./data/vault"
  trash_path: "./data/vault/.trash"

# Safety & Human-in-the-Loop Policies
safety:
  require_approval_on_mutation: true         # Code-level safety gate
  approval_timeout_seconds: 60               # Seconds before auto-cancelling pending mutation
  safe_tools_override: []                    # Explicit whitelist to bypass HITL (advanced)

# Background Daemon & Scheduled Briefings
daemon:
  enabled: true
  morning_briefing_time: "07:30"             # Local 24h format for daily briefing generation
  email_poll_interval_minutes: 15            # Interval for checking incoming email headers
  sync_calendar_interval_minutes: 30         # Interval for updating cached calendar events

# Logging & Telemetry
logging:
  level: "INFO"                              # "DEBUG", "INFO", "WARNING", "ERROR"
  log_to_stdout: true
  audit_to_db: true                          # Record all tool calls and approvals in aether.db
```

---

## 3. MCP Server Registry (`config/mcp_servers.json`)

The orchestrator reads `config/mcp_servers.json` to discover, configure, and spawn tool subprocesses over `stdio`:

```json
{
  "mcpServers": {
    "notes": {
      "command": "python",
      "args": ["src/servers/notes_server.py"],
      "env": {
        "AETHER_VAULT_DIR": "./data/vault"
      },
      "auto_restart": true
    },
    "calendar": {
      "command": "python",
      "args": ["src/servers/calendar_server.py"],
      "env": {
        "CALENDAR_PROVIDER": "caldav",
        "CALENDAR_URL": "http://localhost:5232",
        "CALENDAR_USER": "aether_user"
      },
      "auto_restart": true
    },
    "mail": {
      "command": "python",
      "args": ["src/servers/mail_server.py"],
      "env": {
        "IMAP_SERVER": "imap.example.com",
        "IMAP_PORT": "993",
        "IMAP_USER": "user@example.com",
        "IMAP_USE_SSL": "true"
      },
      "auto_restart": true
    }
  }
}
```

---

## 4. Credential & Secret Management

> [!CAUTION]
> **Zero Credential Exposure Rule**:
> Passwords, API tokens, and secret keys must **never** appear in `config.yaml`, `mcp_servers.json`, or inside model prompt templates.

### 4.1 Secret Loading Protocol

1. **Environment Variables**: The orchestrator and MCP servers load secrets from a local `.env` file (excluded via `.gitignore`) using `python-dotenv`:
   ```bash
   # .env (Never commit this file!)
   IMAP_PASSWORD="your-secure-imap-app-password"
   CALENDAR_PASSWORD="your-secure-caldav-password"
   GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
   ```
2. **Subprocess Isolation**: When spawning an MCP server, the MCP Client Manager injects environment variables only into that specific child process. The calendar server cannot inspect the mail server's credentials, and the LLM context never sees them.
