"""FastMCP server for local Markdown notes, daily notes, and task tracking."""
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from fastmcp import FastMCP

mcp = FastMCP("NotesAndTasks")


def _try_sync_fts(file_path: Path) -> None:
    """Best-effort background sync of modified note into SQLite FTS5 index."""
    try:
        from src.storage.db import DatabaseManager
        db = DatabaseManager()
        db.index_vault_file(file_path, get_vault_dir())
    except Exception:
        pass


def get_vault_dir() -> Path:
    """Resolve and initialize the active Markdown vault directory."""
    vault_str = os.environ.get("AETHER_VAULT_DIR", "./data/vault")
    vault_dir = Path(vault_str).resolve()
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "daily").mkdir(parents=True, exist_ok=True)
    (vault_dir / "projects").mkdir(parents=True, exist_ok=True)
    (vault_dir / ".trash").mkdir(parents=True, exist_ok=True)
    return vault_dir


def resolve_safe_path(rel_path: str, default_ext: str = ".md") -> Path:
    """Resolve a target file within the vault, sandboxing against path traversal attacks."""
    vault_dir = get_vault_dir()

    # Normalize relative path and ensure default extension if missing
    clean_path = rel_path.strip().replace("\\", "/")
    if not clean_path.endswith(default_ext) and not clean_path.endswith(".txt"):
        clean_path = f"{clean_path}{default_ext}"

    # Handle project paths without 'projects/' prefix
    target_path = (vault_dir / clean_path).resolve()

    # Strict sandbox check: must be inside vault_dir and not in .trash
    trash_dir = (vault_dir / ".trash").resolve()
    if (
        not target_path.is_relative_to(vault_dir)
        or target_path == trash_dir
        or trash_dir in target_path.parents
        or ".trash" in target_path.parts
    ):
        raise PermissionError(f"Access denied: path '{rel_path}' resolves outside the vault sandbox.")

    return target_path


@mcp.tool()
def search_notes(
    query: str = "",
    tag: str | None = None,
    limit: int = 5,
    keywords: Any = None,
    tag_filter: Any = None,
) -> list[dict[str, Any]]:
    """Search notes across the Markdown vault by keywords and optional tag filter."""
    if not query and keywords:
        if isinstance(keywords, list):
            query = " ".join(str(k) for k in keywords)
        else:
            query = str(keywords)

    if not tag and tag_filter:
        if isinstance(tag_filter, list) and tag_filter:
            tag = str(tag_filter[0])
        elif isinstance(tag_filter, str):
            tag = tag_filter

    vault_dir = get_vault_dir()
    results: list[dict[str, Any]] = []
    query_lower = query.lower()
    tag_clean = tag.lstrip("#").lower() if tag else None

    for file_path in vault_dir.rglob("*.md"):
        # Exclude trash
        if ".trash" in file_path.parts:
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        rel_name = file_path.relative_to(vault_dir).as_posix()
        lines = content.splitlines()
        current_heading = "Top"

        for line_idx, line in enumerate(lines):
            line_stripped = line.strip()
            if line_stripped.startswith("#"):
                current_heading = line_stripped

            tag_matched = True
            if tag_clean:
                # Check for #tag in line
                tag_matched = f"#{tag_clean}" in line.lower() or f"tags: {tag_clean}" in content.lower()

            if tag_matched and query_lower in line.lower():
                # Extract snippet with surrounding context
                start = max(0, line_idx - 1)
                end = min(len(lines), line_idx + 2)
                snippet = "\n".join(lines[start:end])

                results.append({
                    "file": rel_name,
                    "heading": current_heading,
                    "snippet": snippet,
                    "line": line_idx + 1,
                })

                if len(results) >= limit:
                    return results

    return results


@mcp.tool()
def read_project_notes(project: str = "Inbox", project_name: str | None = None) -> str:
    """Read the full content of a project's Markdown note."""
    target_project = project_name or project
    try:
        # Check root or projects/ directory
        vault_dir = get_vault_dir()
        target = resolve_safe_path(target_project)
        if not target.exists():
            # Try looking under projects/
            alt_target = resolve_safe_path(f"projects/{target_project}")
            if alt_target.exists():
                target = alt_target

        if not target.exists():
            return f"Note '{target_project}' does not exist in vault."

        return target.read_text(encoding="utf-8")
    except PermissionError as e:
        return f"Error: {e}"


@mcp.tool()
def read_daily_note(date_str: str | None = None, date: str | None = None) -> str:
    """Read the daily note for a given ISO date string (YYYY-MM-DD)."""
    from datetime import datetime

    actual_date = date_str or date or datetime.now().strftime("%Y-%m-%d")
    try:
        clean_date = actual_date.strip()
        target = resolve_safe_path(f"daily/{clean_date}.md")
        if not target.exists():
            return f"Daily note for {clean_date} does not exist."
        return target.read_text(encoding="utf-8")
    except PermissionError as e:
        return f"Error: {e}"


def infer_priority_from_text(text: str) -> str:
    """Infer task priority from natural language text if not explicitly designated."""
    t_lower = text.lower()
    urgent_patterns = [
        r"\burgent\b", r"\basap\b", r"\bemergency\b", r"\bcritical\b",
        r"\bimmediately\b", r"\bright now\b", r"\bhighest priority\b", r"#urgent\b"
    ]
    important_patterns = [
        r"\bimportant\b", r"\bhigh priority\b", r"\bcrucial\b", r"\bvital\b",
        r"\bsignificant\b", r"\bkey task\b", r"#important\b"
    ]
    for pat in urgent_patterns:
        if re.search(pat, t_lower):
            return "urgent"
    for pat in important_patterns:
        if re.search(pat, t_lower):
            return "important"
    return "normal"


@mcp.tool()
def add_todo_item(
    task: Any = "",
    project: str = "Inbox",
    due_date: str | None = None,
    priority: str | None = None,
    todo: Any = None,
    text: Any = None,
    project_name: str | None = None,
    section: str | None = None,
    items: Any = None,
    tasks: Any = None,
    todos: Any = None,
    content: Any = None,
    title: Any = None,
    description: Any = None,
) -> dict[str, Any]:
    """Add one or more checklist tasks (- [ ]) with optional due date and priority to a project or Inbox note."""
    target_project = project_name or section or project
    try:
        target = resolve_safe_path(target_project)
        target.parent.mkdir(parents=True, exist_ok=True)

        # Collect raw task candidates
        raw = task or todo or text or items or tasks or todos or content or title or description or ""

        # Flatten into a list of task strings
        task_list: list[str] = []
        if isinstance(raw, (list, tuple, set)):
            for item in raw:
                if isinstance(item, dict):
                    t_str = str(item.get("task") or item.get("text") or item.get("title") or item.get("name") or "").strip()
                else:
                    t_str = str(item).strip()
                if t_str:
                    task_list.append(t_str)
        elif isinstance(raw, str):
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if lines:
                task_list.extend(lines)
            elif raw.strip():
                task_list.append(raw.strip())
        elif raw:
            task_list.append(str(raw).strip())

        if not task_list:
            return {
                "status": "error",
                "message": "No task text provided to add.",
            }

        entries: list[str] = []
        overall_pri = (priority or "").strip().lower()

        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        prefix = "\n" if existing and not existing.endswith("\n") else ""
        text_to_append = ""
        task_priorities: list[str] = []

        for single_task in task_list:
            clean = re.sub(r"^[-*]\s*(\[[ xX]?\]\s*)?", "", single_task).strip()
            if not clean:
                continue

            pri = overall_pri if overall_pri in ("urgent", "important", "normal") else infer_priority_from_text(clean)
            task_priorities.append(pri)
            entry = f"- [ ] {clean}"
            if pri in ("urgent", "important"):
                entry += f" priority::{pri}"
            if due_date:
                entry += f" due::{due_date.strip()}"

            entries.append(entry)
            text_to_append += f"{entry}\n"

        if not entries:
            return {
                "status": "error",
                "message": "No valid task items could be parsed.",
            }

        with open(target, "a", encoding="utf-8") as f:
            f.write(f"{prefix}{text_to_append}")

        _try_sync_fts(target)

        return {
            "status": "success",
            "file": target.name,
            "entry": entries[0] if len(entries) == 1 else entries,
            "count": len(entries),
            "priority": task_priorities[0] if len(task_priorities) == 1 else (overall_pri if overall_pri in ("urgent", "important", "normal") else "normal"),
            "message": f"Added {len(entries)} task(s) to {target.name}",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to add task: {e}",
        }


@mcp.tool()
def append_note(project: str, content: str, section: str | None = None) -> dict[str, Any]:
    """Safely append markdown content under an optional section heading without overwriting."""
    try:
        target = resolve_safe_path(project)
        target.parent.mkdir(parents=True, exist_ok=True)

        text_to_append = ""
        if not target.exists():
            text_to_append += f"# {Path(project).stem}\n\n"

        if section:
            sec_header = section.strip()
            if not sec_header.startswith("#"):
                sec_header = f"## {sec_header}"
            text_to_append += f"\n{sec_header}\n{content.strip()}\n"
        else:
            text_to_append += f"\n{content.strip()}\n"

        with open(target, "a", encoding="utf-8") as f:
            f.write(text_to_append)

        _try_sync_fts(target)

        return {
            "status": "success",
            "file": target.name,
            "bytes_written": len(text_to_append),
            "message": f"Successfully appended content to {target.name}",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to append note: {e}",
        }


@mcp.tool()
def prune_old_completed_tasks(max_age_days: int = 14) -> int:
    """Auto-delete completed checklist tasks (- [x] or - [X]) older than max_age_days across the vault."""
    vault_dir = get_vault_dir()
    cutoff_date = datetime.now().date() - timedelta(days=max_age_days)
    total_pruned = 0

    for file_path in vault_dir.rglob("*.md"):
        if ".trash" in file_path.parts:
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if "- [x]" not in content and "- [X]" not in content:
            continue

        lines = content.splitlines()
        new_lines: list[str] = []
        file_modified = False

        daily_match = re.search(r"(\d{4}-\d{2}-\d{2})\.md$", file_path.name)
        daily_file_date: date | None = None
        if daily_match:
            try:
                daily_file_date = datetime.strptime(daily_match.group(1), "%Y-%m-%d").date()
            except ValueError:
                daily_file_date = None

        file_mtime_date = datetime.fromtimestamp(file_path.stat().st_mtime).date()

        for line in lines:
            stripped = line.strip()
            is_completed = stripped.startswith("- [x]") or stripped.startswith("- [X]")

            if not is_completed:
                new_lines.append(line)
                continue

            # Determine task completion date
            task_date: date | None = None

            # 1. Check for explicit completion timestamp tag
            comp_match = re.search(r"(?:completed::|@completed\(|\[completed:\s*|✅\s*)(\d{4}-\d{2}-\d{2})", stripped)
            if comp_match:
                try:
                    task_date = datetime.strptime(comp_match.group(1), "%Y-%m-%d").date()
                except ValueError:
                    task_date = None

            # 2. Check for due date if present (e.g. due::2026-08-20)
            if not task_date:
                due_match = re.search(r"due::(\d{4}-\d{2}-\d{2})", stripped)
                if due_match:
                    try:
                        task_date = datetime.strptime(due_match.group(1), "%Y-%m-%d").date()
                    except ValueError:
                        task_date = None

            # 3. Check daily note date
            if not task_date and daily_file_date:
                task_date = daily_file_date

            # 4. Fallback to file mtime
            if not task_date:
                task_date = file_mtime_date

            if task_date and task_date < cutoff_date:
                file_modified = True
                total_pruned += 1
            else:
                new_lines.append(line)

        if file_modified:
            try:
                file_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                _try_sync_fts(file_path)
            except Exception:
                pass

    return total_pruned


@mcp.tool()
def list_todos(
    project: str | None = None,
    status: str = "pending",
    limit: int = 50,
    priority: str | None = None,
) -> list[dict[str, Any]]:
    """List markdown checklist tasks (- [ ] or - [x]) across the vault or within a specific note.

    Args:
        project: Optional note/project name (e.g. 'Inbox' or 'daily/2026-09-05'). If None, scans all vault notes.
        status: Filter by status: 'pending' (default, - [ ]), 'completed' (- [x]), or 'all'.
        limit: Maximum number of tasks to return (default: 50).
        priority: Filter by priority: 'urgent', 'important', 'normal', or 'all' (default: None/all).
    """
    # Auto-prune completed tasks older than 14 days to prevent list flooding
    prune_old_completed_tasks(max_age_days=14)

    vault_dir = get_vault_dir()
    todos: list[dict[str, Any]] = []

    if project:
        try:
            target = resolve_safe_path(project)
            target_files = [target] if target.exists() else []
        except Exception:
            target_files = []
    else:
        target_files = [f for f in vault_dir.rglob("*.md") if ".trash" not in f.parts]

    for file_path in target_files:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        rel_name = file_path.relative_to(vault_dir).as_posix()
        for idx, line in enumerate(content.splitlines()):
            stripped = line.strip()
            is_pending = stripped.startswith("- [ ]")
            is_completed = stripped.startswith("- [x]") or stripped.startswith("- [X]")

            if not (is_pending or is_completed):
                continue

            if status == "pending" and not is_pending:
                continue
            if status == "completed" and not is_completed:
                continue

            # Extract task text without checklist syntax
            raw_text = stripped[5:].strip()

            # Clean completion tags if present
            clean_text = re.sub(r"\[?completed::[^\s\]]+\]?", "", raw_text).strip()
            clean_text = re.sub(r"@completed\([^\)]+\)", "", clean_text).strip()

            # Parse priority if present (e.g. 'priority::urgent', 'priority::important', 'priority::normal')
            priority_match = re.search(r"\[?priority::(urgent|important|normal)\]?", clean_text, re.IGNORECASE)
            if priority_match:
                task_priority = priority_match.group(1).lower()
            else:
                # Fallback to hashtag detection (#urgent, #important)
                if re.search(r"#urgent\b", clean_text, re.IGNORECASE):
                    task_priority = "urgent"
                elif re.search(r"#important\b", clean_text, re.IGNORECASE):
                    task_priority = "important"
                else:
                    task_priority = "normal"

            # Clean out priority tag from display text
            clean_text = re.sub(r"\[?priority::[^\s\]]+\]?", "", clean_text).strip()

            # Parse due date if present (e.g. 'due::2026-09-10')
            due_match = re.search(r"due::([^\s]+)", clean_text)
            due_date = due_match.group(1) if due_match else None
            clean_text = re.sub(r"due::[^\s]+", "", clean_text).strip()

            # Parse tags
            tags = re.findall(r"#([a-zA-Z0-9_\-]+)", clean_text)

            if priority and priority.lower() != "all" and task_priority != priority.lower():
                continue

            status_str = "completed" if is_completed else "pending"
            todos.append({
                "id": f"{rel_name}:{idx + 1}",
                "file": rel_name,
                "line": idx + 1,
                "text": clean_text,
                "status": status_str,
                "completed": is_completed,
                "priority": task_priority,
                "due": due_date,
                "due_date": due_date,
                "tags": tags,
                "raw": stripped,
            })

            if len(todos) >= limit:
                return todos

    return todos


@mcp.tool()
def update_todo_priority(
    task_query: str,
    priority: str,
    project: str = "Inbox",
    file_name: str | None = None,
) -> dict[str, Any]:
    """Update the priority (urgent, important, normal) of a checklist task in the vault."""
    target_project = file_name or project
    clean_priority = (priority or "normal").strip().lower()
    if clean_priority not in ("urgent", "important", "normal"):
        return {"status": "error", "message": f"Invalid priority '{priority}'. Must be 'urgent', 'important', or 'normal'."}

    try:
        vault_dir = get_vault_dir()
        target = resolve_safe_path(target_project)
        if not target.exists():
            matched_file = None
            for f in vault_dir.rglob("*.md"):
                if ".trash" in f.parts:
                    continue
                try:
                    c = f.read_text(encoding="utf-8", errors="ignore")
                    if ("- [ ]" in c or "- [x]" in c) and task_query.lower() in c.lower():
                        matched_file = f
                        break
                except Exception:
                    continue
            if not matched_file:
                return {"status": "error", "message": f"Task matching '{task_query}' not found."}
            target = matched_file

        lines = target.read_text(encoding="utf-8").splitlines()
        modified = False
        updated_line = ""

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if (stripped.startswith("- [ ]") or stripped.startswith("- [x]")) and task_query.lower() in stripped.lower():
                # Replace existing priority or append new one
                if re.search(r"priority::[^\s]+", line):
                    new_line = re.sub(r"priority::[^\s]+", f"priority::{clean_priority}", line)
                else:
                    new_line = f"{line.rstrip()} priority::{clean_priority}"
                lines[idx] = new_line
                updated_line = new_line.strip()
                modified = True
                break

        if modified:
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            _try_sync_fts(target)
            return {
                "status": "success",
                "file": target.name,
                "task": updated_line,
                "priority": clean_priority,
                "message": f"Updated priority to {clean_priority} in {target.name}",
            }
        else:
            return {"status": "error", "message": f"Task matching '{task_query}' not found in {target.name}."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to update task priority: {e}"}


@mcp.tool()
def complete_todo(
    task_query: str,
    project: str = "Inbox",
    file_name: str | None = None,
) -> dict[str, Any]:
    """Mark a pending task (- [ ]) as completed (- [x]) by matching keywords in its text."""
    target_project = file_name or project
    try:
        vault_dir = get_vault_dir()
        target = resolve_safe_path(target_project)
        if not target.exists():
            # Try searching across vault if not found in target
            matched_file = None
            for f in vault_dir.rglob("*.md"):
                if ".trash" in f.parts:
                    continue
                try:
                    c = f.read_text(encoding="utf-8", errors="ignore")
                    if "- [ ]" in c and task_query.lower() in c.lower():
                        matched_file = f
                        break
                except Exception:
                    continue
            if not matched_file:
                return {"status": "error", "message": f"Task matching '{task_query}' not found."}
            target = matched_file

        lines = target.read_text(encoding="utf-8").splitlines()
        modified = False
        completed_line = ""

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("- [ ]") and task_query.lower() in stripped.lower():
                # Replace "- [ ]" with "- [x]" preserving indentation and attaching completion date
                today_str = datetime.now().strftime("%Y-%m-%d")
                completed_line_body = line.replace("- [ ]", "- [x]", 1)
                if "completed::" not in completed_line_body and "@completed" not in completed_line_body:
                    lines[idx] = f"{completed_line_body} [completed::{today_str}]"
                else:
                    lines[idx] = completed_line_body
                completed_line = lines[idx].strip()
                modified = True
                break

        if modified:
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return {
                "status": "success",
                "file": target.name,
                "task": completed_line,
                "message": f"Checked off task in {target.name}",
            }
        else:
            return {"status": "error", "message": f"No pending task matching '{task_query}' in {target.name}."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to complete task: {e}"}


@mcp.tool()
def delete_todo(
    task_query: str,
    project: str = "Inbox",
    file_name: str | None = None,
) -> dict[str, Any]:
    """Remove a task line from a note by matching keywords in its text."""
    target_project = file_name or project
    try:
        target = resolve_safe_path(target_project)
        if not target.exists():
            return {"status": "error", "message": f"Note '{target_project}' does not exist."}

        lines = target.read_text(encoding="utf-8").splitlines()
        new_lines = []
        removed = False
        removed_text = ""

        for line in lines:
            stripped = line.strip()
            if (stripped.startswith("- [ ]") or stripped.startswith("- [x]")) and task_query.lower() in stripped.lower() and not removed:
                removed = True
                removed_text = stripped
                continue
            new_lines.append(line)

        if removed:
            target.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            return {
                "status": "success",
                "file": target.name,
                "removed_task": removed_text,
                "message": f"Removed task from {target.name}",
            }
        else:
            return {"status": "error", "message": f"No task matching '{task_query}' found in {target.name}."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to delete task: {e}"}


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
