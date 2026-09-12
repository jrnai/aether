"""SQLite Database Manager for Project Aether."""
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def get_default_db_path() -> Path:
    """Return the default SQLite database path."""
    env_path = os.environ.get("AETHER_DB_PATH")
    if env_path:
        return Path(env_path).resolve()
    data_dir = Path(os.environ.get("AETHER_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "aether.db"


class DatabaseManager:
    """Manages SQLite storage, session persistence, and audit logging."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path).resolve() if db_path else get_default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Return a thread-local configured SQLite connection, caching per thread."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        """Close thread-local connection if open."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None


    def _init_db(self) -> None:
        """Initialize required database tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executescript("""
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
                    tool_calls_json TEXT,
                    tool_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                -- 3. Comprehensive Audit Log
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    is_mutating BOOLEAN NOT NULL,
                    requires_approval BOOLEAN NOT NULL,
                    user_approved BOOLEAN,
                    execution_status TEXT CHECK(execution_status IN ('SUCCESS', 'ERROR', 'CANCELLED', 'TIMEOUT')),
                    duration_ms INTEGER,
                    result_preview TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- 4. Cached Calendar Events
                CREATE TABLE IF NOT EXISTS cached_events (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP NOT NULL,
                    location TEXT,
                    description TEXT,
                    last_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- 5. Cached Email Summaries
                CREATE TABLE IF NOT EXISTS cached_emails (
                    id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    date_received TIMESTAMP NOT NULL,
                    snippet TEXT,
                    processed_for_briefing BOOLEAN DEFAULT FALSE,
                    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- 6. System State (Key-Value persistence for daemon/briefings)
                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- 7. Full-Text Search (SQLite FTS5 for Vault Notes)
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                    file_path UNINDEXED,
                    heading,
                    content,
                    tokenize = 'porter unicode61'
                );

                -- 8. Cached Tech News (Hacker News Algolia & Google News RSS)
                CREATE TABLE IF NOT EXISTS cached_news (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    score INTEGER DEFAULT 0,
                    comments_count INTEGER DEFAULT 0,
                    author TEXT,
                    published_at TIMESTAMP,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    summary TEXT,
                    image_url TEXT,
                    category TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_cached_news_published ON cached_news(published_at DESC);
                CREATE INDEX IF NOT EXISTS idx_cached_news_source ON cached_news(source);
            """)

            # Lightweight schema migration for existing cached_news tables
            for col in ("summary TEXT", "image_url TEXT", "category TEXT"):
                try:
                    conn.execute(f"ALTER TABLE cached_news ADD COLUMN {col}")
                except Exception:
                    pass

            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_news_category ON cached_news(category)")
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Sessions & Messages
    # -------------------------------------------------------------------------

    def create_session(self, session_id: str | None = None, title: str = "CLI Session") -> str:
        """Create and return a new session ID."""
        sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        now = datetime.now().astimezone().isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (sid, title, now, now),
            )
        return sid

    def get_or_create_session(self, session_id: str, title: str = "CLI Session") -> str:
        """Get an existing session or create it if missing."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row:
                return row["id"]
        return self.create_session(session_id=session_id, title=title)

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str | None = None,
        tool_calls_json: str | None = None,
        tool_name: str | None = None,
    ) -> int:
        """Store a chat message in the session history."""
        now = datetime.now().astimezone().isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (session_id, role, content, tool_calls_json, tool_name, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, tool_calls_json, tool_name, now),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            return cursor.lastrowid or 0

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve all messages for a given session in chronological order."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, session_id, role, content, tool_calls_json, tool_name, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Audit Logging
    # -------------------------------------------------------------------------

    def log_audit(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        is_mutating: bool,
        requires_approval: bool,
        user_approved: bool | None,
        execution_status: str,
        duration_ms: int = 0,
        result_preview: str | None = None,
        session_id: str | None = None,
    ) -> int:
        """Log a tool execution event into the audit trail."""
        now = datetime.now().astimezone().isoformat()
        args_str = json.dumps(arguments, ensure_ascii=False)
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_logs (
                    session_id, tool_name, arguments_json, is_mutating,
                    requires_approval, user_approved, execution_status,
                    duration_ms, result_preview, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    tool_name,
                    args_str,
                    is_mutating,
                    requires_approval,
                    user_approved,
                    execution_status,
                    duration_ms,
                    result_preview,
                    now,
                ),
            )
            return cursor.lastrowid or 0

    def get_audit_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve recent audit logs in reverse chronological order."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Caching Helpers
    # -------------------------------------------------------------------------

    def cache_event(
        self,
        event_id: str,
        title: str,
        start_time: str,
        end_time: str,
        location: str = "",
        description: str = "",
    ) -> None:
        """Upsert a calendar event into the local cache."""
        now = datetime.now().astimezone().isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO cached_events (id, title, start_time, end_time, location, description, last_synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    start_time=excluded.start_time,
                    end_time=excluded.end_time,
                    location=excluded.location,
                    description=excluded.description,
                    last_synced_at=excluded.last_synced_at
                """,
                (event_id, title, start_time, end_time, location, description, now),
            )

    def cache_email(
        self,
        email_id: str,
        sender: str,
        subject: str,
        date_received: str,
        snippet: str = "",
        processed: bool = False,
    ) -> None:
        """Upsert an email summary into the local cache."""
        now = datetime.now().astimezone().isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO cached_emails (id, sender, subject, date_received, snippet, processed_for_briefing, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    sender=excluded.sender,
                    subject=excluded.subject,
                    date_received=excluded.date_received,
                    snippet=excluded.snippet,
                    processed_for_briefing=excluded.processed_for_briefing,
                    indexed_at=excluded.indexed_at
                """,
                (email_id, sender, subject, date_received, snippet, processed, now),
            )

    def cache_news_items(self, items: list[dict[str, Any]]) -> int:
        """Upsert a list of news items into the local cache."""
        if not items:
            return 0
        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()
        records = [
            (
                item["id"],
                item["title"],
                item["url"],
                item.get("source", "Tech News"),
                int(item.get("score") or 0),
                int(item.get("comments_count") or 0),
                item.get("author") or "",
                item.get("published_at") or now,
                now,
                item.get("summary") or "",
                item.get("image_url") or "",
                item.get("category") or "tech",
            )
            for item in items
        ]
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO cached_news (id, title, url, source, score, comments_count, author, published_at, fetched_at, summary, image_url, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    url=excluded.url,
                    source=excluded.source,
                    score=excluded.score,
                    comments_count=excluded.comments_count,
                    author=excluded.author,
                    published_at=excluded.published_at,
                    fetched_at=excluded.fetched_at,
                    summary=excluded.summary,
                    image_url=excluded.image_url,
                    category=excluded.category
                """,
                records,
            )
        return len(records)

    def get_cached_news(
        self,
        limit: int = 30,
        source: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve cached news headlines ordered by published_at DESC, score DESC."""
        with self._get_connection() as conn:
            clauses = []
            params: list[Any] = []
            if source and source.lower() not in ("all", "*"):
                clauses.append("LOWER(source) = LOWER(?)")
                params.append(source)
            if category and category.lower() not in ("all", "*"):
                clauses.append("LOWER(category) = LOWER(?)")
                params.append(category)

            where_str = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            query = f"""
                SELECT id, title, url, source, score, comments_count, author, published_at, fetched_at, summary, image_url, category
                FROM cached_news
                {where_str}
                ORDER BY published_at DESC, score DESC
                LIMIT ?
            """
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def prune_old_news(self, max_age_hours: int = 72) -> int:
        """Remove cached news items older than max_age_hours to prevent database bloat."""
        from datetime import timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM cached_news WHERE fetched_at < ? AND published_at < ?",
                (cutoff, cutoff),
            )
            return cursor.rowcount

    # -------------------------------------------------------------------------
    # System State (Key-Value)
    # -------------------------------------------------------------------------

    def get_state(self, key: str, default: str | None = None) -> str | None:
        """Retrieve a stored system state value by key."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT value FROM system_state WHERE key = ?", (key,)).fetchone()
            if row:
                return str(row["value"])
        return default

    def set_state(self, key: str, value: str) -> None:
        """Store or update a system state value by key."""
        now = datetime.now().astimezone().isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO system_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (key, str(value), now),
            )

    # -------------------------------------------------------------------------
    # Full-Text Search (FTS5) for Notes
    # -------------------------------------------------------------------------

    def sync_note_fts(self, file_path: str, heading: str, content: str) -> None:
        """Insert a note section into the FTS5 full-text index."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO notes_fts (file_path, heading, content) VALUES (?, ?, ?)",
                (file_path, heading, content),
            )

    def delete_note_fts(self, file_path: str) -> None:
        """Remove a note from the FTS5 index."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM notes_fts WHERE file_path = ?", (file_path,))

    def index_vault_file(self, file_path: Path, vault_dir: Path) -> int:
        """Parse headings and content in a Markdown file and index into notes_fts."""
        rel_path = file_path.relative_to(vault_dir).as_posix()
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return 0

        self.delete_note_fts(rel_path)

        lines = text.splitlines()
        current_heading = "Top"
        chunk_lines: list[str] = []
        indexed_count = 0

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                if chunk_lines:
                    self.sync_note_fts(rel_path, current_heading, "\n".join(chunk_lines))
                    indexed_count += 1
                    chunk_lines = []
                current_heading = stripped
            else:
                chunk_lines.append(line)

        if chunk_lines:
            self.sync_note_fts(rel_path, current_heading, "\n".join(chunk_lines))
            indexed_count += 1

        return indexed_count

    def index_vault(self, vault_dir: Path | str) -> int:
        """Scan and index all Markdown notes across a vault directory into FTS5."""
        vdir = Path(vault_dir).resolve()
        total_sections = 0
        for md_file in vdir.rglob("*.md"):
            if ".trash" in md_file.parts:
                continue
            total_sections += self.index_vault_file(md_file, vdir)
        return total_sections

    def search_notes_fts(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search notes_fts virtual table using SQLite FTS5 MATCH syntax."""
        clean_query = query.strip().replace('"', '""')
        if not clean_query:
            return []

        tokens = [t for t in clean_query.split() if t.isalnum()]
        if not tokens:
            fts_expression = f'"{clean_query}"'
        else:
            fts_expression = " OR ".join(f"{tok}*" for tok in tokens)

        with self._get_connection() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT file_path, heading, snippet(notes_fts, 2, '', '', '...', 15) as snippet, rank
                    FROM notes_fts
                    WHERE notes_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_expression, limit),
                ).fetchall()
                return [
                    {
                        "file": row["file_path"],
                        "heading": row["heading"],
                        "snippet": row["snippet"],
                        "rank": row["rank"],
                    }
                    for row in rows
                ]
            except Exception as e:
                logger.warning("FTS search failed for query '%s': %s", query, e)
                return []


def make_sqlite_audit_logger(db: DatabaseManager, session_id: str | None = None) -> Any:
    """Create a callback for SafetyGuard that writes ToolSafetyAction to SQLite audit_logs."""
    def audit_callback(action: Any) -> None:
        execution_status = "SUCCESS"
        if action.requires_approval and action.user_approved is False:
            execution_status = "CANCELLED"

        db.log_audit(
            tool_name=action.tool_name,
            arguments=action.arguments,
            is_mutating=not action.is_safe,
            requires_approval=action.requires_approval,
            user_approved=action.user_approved,
            execution_status=execution_status,
            session_id=session_id,
        )
    return audit_callback

