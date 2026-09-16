# ADR-006: AST Command Sandboxing & HITL Safety Gates

## Status
**Accepted** (2026-08)

## Context
Project Aether functions as an autonomous coding agent with capabilities to execute terminal commands, edit source files, delete files, and stage email drafts.

Allowing an LLM unrestricted execution of terminal commands (`shell=True`) exposes the host workstation to catastrophic failure modes:
1. **Destructive Hallucinations**: Small models may emit disk formatting commands, recursive deletions (`rm -rf /`, `rmdir /s /q C:\`), or kill system processes.
2. **Indirect Prompt Injection**: Malicious instructions embedded in incoming emails or fetched web pages could attempt to exfiltrate private files or install malware via subshell execution (`curl ... | bash`, `Invoke-Expression`, `$()`).

## Decision
We implemented a two-tier safety architecture ([`src/agent/guardrails.py`](file:///C:/Users/jrrya/Projects/aether/src/agent/guardrails.py), [`src/servers/files_server.py`](file:///C:/Users/jrrya/Projects/aether/src/servers/files_server.py)):

### 1. Terminal Command Sandbox (`validate_terminal_command`)
- Commands are split using `shlex` across subshells, pipes (`|`), and chained operators (`&&`, `||`, `;`).
- Command substitution tokens (`$()`, `` ` ``, `${}`) are unconditionally rejected.
- Binaries must strictly match an `ALLOWED_BINARIES` allowlist (`git`, `python`, `pytest`, `cargo`, `npm`, `tsc`, `dir`, `echo`, etc.).
- Explicitly blocked destructive patterns (`rm -rf`, `mkfs`, `dd if=`, `format`, `del /s`) fail immediately.
- Paths are resolved to verify operations remain within the active workspace root directory.

### 2. Human-in-the-Loop (HITL) Interceptor (`SafetyGuard`)
- Tools are categorized into **Safe (Read-Only)** vs **Mutating (Destructive)**.
- Safe tools (`search_web`, `files_read_file`, `calendar_list_events`) execute automatically without friction.
- Mutating tools (`send_email`, `files_write_file`, `files_delete_file`, `calendar_delete_event`) halt execution and trigger an interactive approval dialog in the CLI/Web UI.
- All approval outcomes, arguments, and timestamps are logged to the SQLite audit database.

## Consequences
### Positive
- **Guaranteed Workstation Protection**: Accidental or adversarial attempts to modify files outside the workspace are blocked before execution.
- **Auditability**: Every mutating action is captured in `aether.db` with user approval status.
- **Operator Agency**: The user retains ultimate veto power over external communication (emails) and filesystem mutations.

### Negative
- Multi-step automated tasks involving file writes require human confirmation clicks, slightly reducing full "hands-off" autonomy.

## Alternatives Considered
- **Docker Containerization**: Considered running all commands inside local Docker containers. While highly secure, mounting local Windows filesystems into Docker introduces severe file-sync latency and requires Docker Desktop to be running continuously.
- **Unrestricted Whitelist Bypass**: Rejected because autonomous agents must adhere to the principle of least privilege on desktop environments.
