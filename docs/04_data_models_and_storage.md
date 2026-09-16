# Aether Specification 04: Data Models & Storage Architecture

## 1. Storage Overview

Aether adheres to an **offline-first hybrid storage architecture**:

```
                       Storage Architecture
                      ┌─────────────────────┐
                      │    Aether Core      │
                      └──────────┬──────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
    ┌─────────────────────────┐     ┌─────────────────────────┐
    │  SQLite: data/aether.db │     │ File Vault: data/vault/ │
    ├─────────────────────────┤     ├─────────────────────────┤
    │ • Conversation Sessions │     │ • Daily Notes (daily/)  │
    │ • Audit Log & Approvals │     │ • Project Notes (.md)   │
    │ • Calendar/Email Cache  │     │ • Task Checklists       │
    │ • FTS5 & Vector Index   │     │ • Soft-deletes (.trash/)│
    └─────────────────────────┘     └─────────────────────────┘
```

1. **SQLite Database (`data/aether.db`)**: Handles structured application state, full conversational memory, external entity caching, full-text search indexes (FTS5), vector embeddings (via `sqlite-vec`), and tamper-evident audit logs.
2. **Markdown Vault (`data/vault/`)**: The human-facing filesystem store. User notes and tasks reside in readable Markdown files compatible with Obsidian, Logseq, or raw text editors.

---

## 2. Relational Database Schema (`data/aether.db`)

SQLite is configured with:
```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
```

### 2.1 Schema Definitions (DDL)

```sql
-- 1. Conversation Sessions
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Message History
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('system', 'user', 'assistant', 'tool')),
    content TEXT,
    tool_calls_json TEXT,         -- Serialized tool call requests if role == 'assistant'
    tool_name TEXT,               -- Tool name if role == 'tool'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- 3. Comprehensive Audit Log
-- Records every tool invocation attempt, safety status, human approval outcome, and execution latency.
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    is_mutating BOOLEAN NOT NULL,
    requires_approval BOOLEAN NOT NULL,
    user_approved BOOLEAN,        -- NULL if safe=true, TRUE if approved, FALSE if rejected
    execution_status TEXT CHECK(execution_status IN ('SUCCESS', 'ERROR', 'CANCELLED', 'TIMEOUT')),
    duration_ms INTEGER,
    result_preview TEXT,          -- Truncated tool output for auditing
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Cached Calendar Events
CREATE TABLE IF NOT EXISTS cached_events (
    id TEXT PRIMARY KEY,          -- External UID from CalDAV/Google
    title TEXT NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    location TEXT,
    description TEXT,
    last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Cached Email Summaries
CREATE TABLE IF NOT EXISTS cached_emails (
    id TEXT PRIMARY KEY,          -- Message-ID or IMAP UID
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    date_received TIMESTAMP NOT NULL,
    snippet TEXT,
    processed_for_briefing BOOLEAN DEFAULT FALSE,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 Search & Vector Storage

To achieve sub-50ms local note discovery:

#### Full-Text Search (SQLite FTS5)
For instant keyword, exact phrase, and prefix matching across note headers and paragraphs:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    file_path UNINDEXED,
    heading,
    content,
    tokenize = 'porter unicode61'
);
```

#### Vector Search (`sqlite-vec`)
For conceptual / semantic query matching (e.g., query "server deployment steps" matches a note discussing "Docker production release"):

```sql
-- Using sqlite-vec 384-dimensional embeddings (e.g., sentence-transformers/all-MiniLM-L6-v2)
CREATE VIRTUAL TABLE IF NOT EXISTS notes_vec USING vec0(
    rowid INTEGER PRIMARY KEY,
    embedding float[384]
);
```

---

## 3. Markdown Vault Organization (`data/vault/`)

The vault is designed for zero lock-in. Any Markdown application (Obsidian, VS Code, Logseq) can open `data/vault/` as its active workspace.

### 3.1 Vault Directory Structure

```text
data/vault/
├── daily/                      # Daily notes & automated morning briefings
│   ├── 2026-09-04.md
│   └── 2026-09-05.md
├── projects/                   # Dedicated project documentation & logs
│   ├── Aether.md
│   └── Personal.md
├── Inbox.md                    # Default capture sink for rapid tasks
└── .trash/                     # Soft-delete target (never unlinks directly)
```

### 3.2 File Formatting Standards

#### 1. Todo Tasks
Tasks follow standard GitHub-flavored Markdown checkboxes with optional inline tags:
```markdown
- [ ] Finalize Q3 budget review due::2026-09-05 #finance
- [x] Complete Aether specification suite #dev
```

#### 2. Daily Notes (`data/vault/daily/YYYY-MM-DD.md`)
Created automatically by the morning briefing daemon:
```markdown
# Daily Note: Friday, September 5, 2026

## Morning Briefing
- **Schedule**: 2 meetings scheduled today (Architecture Sync @ 10:00 AM, 1:1 with Alex @ 2:00 PM).
- **Inbox Triage**: 3 unread emails. 1 urgent item from Sarah regarding budget approvals.

## Priorities for Today
- [ ] Review PR for MCP bridge
- [ ] Prep notes for 1:1

## Scratchpad & Meeting Notes
```

---

## 4. Data Safety & Backup Guarantees

1. **Atomic Appends**: File write operations in `notes_server.py` use append mode (`"a"`) to prevent accidental content erasure.
2. **Soft Deletion**: When an agent operation asks to delete or archive a note, the file is relocated to `data/vault/.trash/` with a timestamp suffix (e.g. `Inbox.md.20260905_120000.bak`).
3. **Database Integrity**: The SQLite database utilizes WAL mode (`PRAGMA journal_mode = WAL;`) allowing concurrent reads while background jobs write to the audit log.
