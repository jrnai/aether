# Aether Specification 02: MCP Server Contracts & Tool Schemas

## 1. Protocol Architecture & Transports

Project Aether leverages the **Model Context Protocol (MCP)** using `fastmcp` (or the official `mcp` Python SDK). All built-in and third-party tools run as independent OS processes communicating with the Aether Orchestrator via **Standard Input / Standard Output (`stdio`)** using JSON-RPC 2.0.

### 1.1 Process Lifecycle

1. **Initialization (`tools/list`)**:
   - The Orchestrator launches the server process (e.g. `python src/servers/notes_server.py`).
   - The Orchestrator issues a standard MCP `initialize` handshake followed by `tools/list`.
   - The server replies with an array of tool descriptors, parameter schemas (JSON Schema Draft 7), and custom metadata.
2. **Tool Execution (`tools/call`)**:
   - The Orchestrator sends a JSON-RPC request containing `name` and `arguments`.
   - The server validates arguments, executes the function, and returns a standard response envelope.
3. **Graceful Shutdown**:
   - The Orchestrator sends `SIGTERM` / closes the `stdin` pipe upon agent exit.

---

## 2. Universal Response & Error Contract

Every tool execution returns a structured response envelope. Even if a tool raises an unhandled exception, it must format the output as a valid MCP response with `isError: true`.

### 2.1 Standard Success Envelope

```json
{
  "status": "success",
  "data": { ... },
  "summary": "Human-readable summary for quick logging"
}
```

### 2.2 Standard Error Envelope

```json
{
  "status": "error",
  "error": {
    "code": "INVALID_ARGUMENT | NOT_FOUND | ACCESS_DENIED | UPSTREAM_ERROR | TIMEOUT",
    "message": "Descriptive error message explaining what failed",
    "details": {}
  }
}
```

---

## 3. Built-In MCP Servers

### 3.1 Notes & Tasks Server (`src/servers/notes_server.py`)

Target vault path: `data/vault/` (configurable via `AETHER_VAULT_DIR`). All operations are sandboxed to this directory.

#### Tool 1: `search_notes`
- **Safety Classification**: Safe / Read-Only (`safe: true`)
- **Description**: Performs keyword or semantic search across the Markdown vault.
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Keywords or search phrase to match in note bodies and headings."
      },
      "tag": {
        "type": "string",
        "description": "Optional tag filter without hash (e.g. 'project', 'finance')."
      },
      "limit": {
        "type": "integer",
        "description": "Maximum number of matching snippets to return (default: 5).",
        "default": 5
      }
    },
    "required": ["query"]
  }
  ```
- **Returns**:
  ```json
  [
    {
      "file": "Projects/Aether.md",
      "heading": "## Roadmap",
      "snippet": "- [ ] Implement MCP server manager\n- [x] Draft specs",
      "score": 0.88
    }
  ]
  ```

#### Tool 2: `add_todo_item`
- **Safety Classification**: Mutating (`safe: false` - Requires Confirmation)
- **Description**: Appends a new todo item with checkbox `- [ ]` and optional due date to a project or Inbox file.
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "task": {
        "type": "string",
        "description": "The description of the task or action item."
      },
      "project": {
        "type": "string",
        "description": "Project filename without extension (default: 'Inbox').",
        "default": "Inbox"
      },
      "due_date": {
        "type": "string",
        "description": "Optional ISO-8601 date string (YYYY-MM-DD) or relative expression."
      }
    },
    "required": ["task"]
  }
  ```
- **Returns**:
  ```json
  {
    "status": "success",
    "file": "Inbox.md",
    "entry": "- [ ] Review draft spec due::2026-09-05"
  }
  ```

#### Tool 3: `read_project_notes`
- **Safety Classification**: Safe / Read-Only (`safe: true`)
- **Description**: Reads the full markdown content of a specified project file.
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "project": {
        "type": "string",
        "description": "The project note name without extension (e.g., 'Work', 'Inbox')."
      }
    },
    "required": ["project"]
  }
  ```
- **Returns**: Plain text string of the note contents.

#### Tool 4: `read_daily_note`
- **Safety Classification**: Safe / Read-Only (`safe: true`)
- **Description**: Loads the daily note from `data/vault/daily/YYYY-MM-DD.md`.
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "date_str": {
        "type": "string",
        "description": "ISO date string in format YYYY-MM-DD."
      }
    },
    "required": ["date_str"]
  }
  ```

#### Tool 5: `append_note`
- **Safety Classification**: Mutating (`safe: false` - Requires Confirmation)
- **Description**: Safely appends a text snippet or section to an existing or new note.
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "project": {
        "type": "string",
        "description": "Project note name without extension."
      },
      "content": {
        "type": "string",
        "description": "Markdown text to append."
      },
      "section": {
        "type": "string",
        "description": "Optional heading under which to append content (e.g. '## Meeting Notes')."
      }
    },
    "required": ["project", "content"]
  }
  ```

---

### 3.2 Calendar Server (`src/servers/calendar_server.py`)

Handles calendar synchronization using local CalDAV protocols (Nextcloud, Apple Calendar, Fastmail) or Google Calendar API.

#### Tool 1: `list_events`
- **Safety Classification**: Safe / Read-Only (`safe: true`)
- **Description**: Queries all calendar events within a given ISO-8601 start and end range.
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "start_iso": {
        "type": "string",
        "description": "Start timestamp in ISO-8601 format (e.g., '2026-09-05T00:00:00Z')."
      },
      "end_iso": {
        "type": "string",
        "description": "End timestamp in ISO-8601 format (e.g., '2026-09-05T23:59:59Z')."
      }
    },
    "required": ["start_iso", "end_iso"]
  }
  ```
- **Returns**:
  ```json
  [
    {
      "id": "cal_evt_101",
      "title": "Weekly Architecture Sync",
      "start": "2026-09-05T10:00:00+08:00",
      "end": "2026-09-05T11:00:00+08:00",
      "location": "Room A / Zoom",
      "description": "Reviewing MCP specs"
    }
  ]
  ```

#### Tool 2: `get_free_slots`
- **Safety Classification**: Safe / Read-Only (`safe: true`)
- **Description**: Scans busy intervals for a given date and returns available time windows during working hours.
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "date_iso": {
        "type": "string",
        "description": "Date in YYYY-MM-DD or full ISO-8601 format."
      },
      "duration_minutes": {
        "type": "integer",
        "description": "Minimum continuous duration required (default: 30).",
        "default": 30
      },
      "work_start_hour": {
        "type": "integer",
        "description": "Start of workday in 24h format (default: 9).",
        "default": 9
      },
      "work_end_hour": {
        "type": "integer",
        "description": "End of workday in 24h format (default: 18).",
        "default": 18
      }
    },
    "required": ["date_iso"]
  }
  ```
- **Returns**:
  ```json
  [
    {"start": "09:00", "end": "10:00", "duration_minutes": 60},
    {"start": "11:30", "end": "14:00", "duration_minutes": 150},
    {"start": "15:30", "end": "18:00", "duration_minutes": 150}
  ]
  ```

#### Tool 3: `create_event`
- **Safety Classification**: Mutating (`safe: false` - Requires Confirmation)
- **Description**: Books a new event on the primary user calendar.
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "title": {
        "type": "string",
        "description": "Event summary/title."
      },
      "start_iso": {
        "type": "string",
        "description": "Event start time in ISO-8601 format."
      },
      "end_iso": {
        "type": "string",
        "description": "Event end time in ISO-8601 format."
      },
      "description": {
        "type": "string",
        "description": "Optional event details or agenda."
      },
      "location": {
        "type": "string",
        "description": "Optional location or virtual conference URL."
      }
    },
    "required": ["title", "start_iso", "end_iso"]
  }
  ```
- **Returns**:
  ```json
  {
    "status": "success",
    "event_id": "cal_evt_202",
    "html_link": "https://calendar.google.com/..."
  }
  ```

---

### 3.3 Mail Server (`src/servers/mail_server.py`)

Interacts with user mail via IMAP/OAuth for fetching, local staging for drafts, and direct SMTP sending with mandatory Human-in-the-Loop authorization.

> [!IMPORTANT]
> **Safety Invariant**: Sending email is a high-risk mutating action. The orchestrator enforces strict Human-in-the-Loop authorization: `send_email` is registered with `safe: false` and halts execution for explicit human confirmation (`[y/N]`) showing recipient, subject, and body before transmitting via SMTP. In addition, emails can be drafted safely offline using `stage_email_draft`.

#### Tool 1: `fetch_unread_emails`
- **Safety Classification**: Safe / Read-Only (`safe: true`)
- **Description**: Fetches unread emails, extracting sanitized text, sender, and dates. All output is wrapped in `<untrusted_content>` tags.
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "limit": {
        "type": "integer",
        "description": "Maximum number of messages to retrieve (default: 10).",
        "default": 10
      },
      "folder": {
        "type": "string",
        "description": "Mailbox folder to check (default: 'INBOX').",
        "default": "INBOX"
      }
    }
  }
  ```
- **Returns**:
  ```json
  [
    {
      "id": "msg_4591",
      "sender": "sarah.connor@example.com",
      "subject": "Q3 Budget Review Reschedule",
      "date": "2026-09-04T18:22:10+08:00",
      "preview": "<untrusted_content source=\"email\" id=\"msg_4591\">\nHey team, can we move tomorrow's review to Friday afternoon?\n</untrusted_content>"
    }
  ]
  ```

#### Tool 2: `stage_email_draft`
- **Safety Classification**: Mutating (`safe: false` - Requires Confirmation)
- **Description**: Stages an email response into the user's `[Drafts]` mailbox or as a `.eml` file on disk. Never sends autonomously.
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "to": {
        "type": "string",
        "description": "Recipient email address."
      },
      "subject": {
        "type": "string",
        "description": "Email subject line."
      },
      "body": {
        "type": "string",
        "description": "Plain-text or Markdown email body."
      },
      "in_reply_to": {
        "type": "string",
        "description": "Optional Message-ID or Aether email ID of thread being replied to."
      }
    },
    "required": ["to", "subject", "body"]
  }
  ```
- **Returns**:
  ```json
  {
    "status": "success",
    "draft_id": "draft_9921",
    "location": "IMAP [Drafts] folder",
    "staged_at": "2026-09-04T21:30:00+08:00"
  }
  ```

#### Tool 3: `send_email`
- **Safety Classification**: Mutating (`safe: false` - Requires Explicit Human Approval)
- **Description**: Directly dispatches an email message over SMTP (e.g. Gmail SSL port 465) after human authorization. Also writes a persistent record to `data/drafts/sent/`.
- **Parameters**:
  ```json
  {
    "type": "object",
    "properties": {
      "to": {
        "type": "string",
        "description": "Recipient email address."
      },
      "subject": {
        "type": "string",
        "description": "Email subject line."
      },
      "body": {
        "type": "string",
        "description": "Email message body."
      },
      "account": {
        "type": "string",
        "description": "Account identifier or label (default: 'personal')."
      },
      "in_reply_to": {
        "type": "string",
        "description": "Optional message ID being replied to."
      }
    },
    "required": ["to", "subject", "body"]
  }
  ```
- **Returns**:
  ```json
  {
    "status": "success",
    "sent_id": "sent_20260905_102000_ab12cd",
    "from": "user@gmail.com",
    "to": "recipient@example.com",
    "subject": "Sync Confirmed",
    "timestamp": "2026-09-05T10:20:00+08:00",
    "message": "Email successfully sent to 'recipient@example.com' from 'user@gmail.com' via smtp.gmail.com."
  }
  ```

---

## 4. MCP Server Registration Format (`config/mcp_servers.json`)

The orchestrator discovers and spawns tool servers using the standard MCP configuration format:

```json
{
  "mcpServers": {
    "notes": {
      "command": "python",
      "args": ["src/servers/notes_server.py"],
      "env": {
        "AETHER_VAULT_DIR": "./data/vault"
      }
    },
    "calendar": {
      "command": "python",
      "args": ["src/servers/calendar_server.py"],
      "env": {
        "CALENDAR_PROVIDER": "caldav",
        "CALENDAR_URL": "http://localhost:5232"
      }
    },
    "mail": {
      "command": "python",
      "args": ["src/servers/mail_server.py"],
      "env": {
        "IMAP_SERVER": "imap.example.com",
        "IMAP_PORT": "993",
        "IMAP_USER": "user@example.com"
      }
    }
  }
}
```
