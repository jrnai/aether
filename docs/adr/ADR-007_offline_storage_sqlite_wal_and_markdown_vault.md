# ADR-007: Embedded SQLite WAL & Markdown Vault vs. Cloud Databases

## Status
**Accepted** (2026-08)

## Context
Aether requires persistent storage for:
1. Structured operational data: session conversation histories, tool execution logs, user approval audits, and cached briefing tokens.
2. User notes and productivity data: daily briefings, task checklists, project notes, and research scratchpads.

Architectural forces:
- **Privacy-First Invariant**: Zero telemetry or user data may leave the workstation.
- **Data Longevity & Ownership**: Users should be able to read, search, edit, and back up their notes without Aether running.
- **Concurrent Reliability**: The web portal and background daemon access the database simultaneously.

## Decision
We implemented a dual-storage strategy ([`src/storage/db.py`](file:///C:/Users/jrrya/Projects/aether/src/storage/db.py), [`src/servers/notes_server.py`](file:///C:/Users/jrrya/Projects/aether/src/servers/notes_server.py)):

### 1. SQLite 3 with Write-Ahead Logging (WAL)
- `data/aether.db` stores sessions, messages, and audit trails.
- Configured with `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` to enable high-throughput concurrent reads and writes between the web server and background daemon without database lock errors.
- Thread-safe connection handling using cached thread-local connections.

### 2. Obsidian/Logseq-Compatible Markdown Vault
- Notes and tasks are stored as plain Markdown files in `data/vault/`.
- Tasks use standard GitHub/Obsidian task checkboxes (`- [ ]`, `- [x]`).
- Daily notes use ISO date filenames (`YYYY-MM-DD.md`).
- A dedicated safe-trash directory (`data/vault/.trash/`) prevents irreversible data loss upon note deletion.

## Consequences
### Positive
- **100% Offline & Private**: Zero external cloud database dependencies (PostgreSQL, Supabase, DynamoDB).
- **Zero Vendor Lock-In**: Users can open their notes vault directly in Obsidian, VS Code, or any plain text editor.
- **Concurrent Performance**: WAL mode prevents lock contention during simultaneous web requests and daemon runs.
- **Trivial Backup**: Backing up the entire application requires copying two local directories (`data/aether.db` and `data/vault/`).

### Negative
- Not natively horizontally scalable across multiple machines (by design, since Aether is an individual workstation assistant).

## Alternatives Considered
- **PostgreSQL / MySQL Container**: Rejected due to unnecessary memory consumption (~200 MB) and container management overhead on personal workstations.
- **Ad-Hoc JSON Files**: Rejected due to lack of ACID transactional guarantees, file corruption risks during sudden power loss or process termination, and poor queryability for audit logs.
