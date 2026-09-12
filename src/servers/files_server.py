"""Safe Filesystem Management, Code Reading/Writing, and Organization Server for Aether."""
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("aether.files")

# Active workspace root override
_ACTIVE_WORKSPACE_ROOT: Path | None = None

# Default excluded directories and files to keep tree and search fast and clean
DEFAULT_EXCLUDED_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "node_modules",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".system_generated",
    ".trash",
}

DEFAULT_EXCLUDED_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "aether.db-shm",
    "aether.db-wal",
    "aether.db-journal",
}

LANG_MAP = {
    "py": "python",
    "js": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "jsx": "javascript",
    "html": "html",
    "htm": "html",
    "css": "css",
    "scss": "css",
    "sass": "css",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "md": "markdown",
    "markdown": "markdown",
    "sql": "sql",
    "sh": "shell",
    "bash": "shell",
    "ps1": "powershell",
    "bat": "batch",
    "cmd": "batch",
    "txt": "plaintext",
    "toml": "toml",
    "xml": "xml",
    "env": "shell",
    "gitignore": "plaintext",
    "ini": "ini",
    "cfg": "ini",
    "conf": "ini",
    "c": "c",
    "cpp": "cpp",
    "h": "c",
    "hpp": "cpp",
    "rs": "rust",
    "go": "go",
    "java": "java",
}

CATEGORY_MAP = {
    "Documents": {".pdf", ".docx", ".doc", ".txt", ".pptx", ".xlsx", ".csv", ".odt", ".rtf"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml", ".sql", ".sh", ".ps1", ".bat", ".c", ".cpp", ".h", ".rs", ".go", ".java", ".toml", ".xml"},
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".tiff"},
    "Archives": {".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".tgz"},
    "Media": {".mp3", ".mp4", ".wav", ".mkv", ".mov", ".avi", ".flac", ".m4a", ".webm"},
}


def get_workspace_root() -> Path:
    """Return the absolute workspace root path."""
    global _ACTIVE_WORKSPACE_ROOT
    if _ACTIVE_WORKSPACE_ROOT and _ACTIVE_WORKSPACE_ROOT.exists():
        return _ACTIVE_WORKSPACE_ROOT
    return Path.cwd().resolve()


def set_workspace_root(new_root: str | Path) -> Path:
    """Dynamically set the active workspace root with smart relative and parent resolution."""
    global _ACTIVE_WORKSPACE_ROOT
    raw = str(new_root).strip().strip('"\'')
    curr = get_workspace_root()

    p = Path(raw)
    if not p.is_absolute():
        # 1. Check relative to current workspace
        candidate = (curr / raw).resolve()
        if candidate.exists() and candidate.is_dir():
            p = candidate
        # 2. Check if user specified the parent directory name (e.g. "Projects" when in "aether")
        elif curr.parent.name.lower() == raw.lower():
            p = curr.parent.resolve()
        # 3. Check relative to current workspace's parent
        elif (curr.parent / raw).exists() and (curr.parent / raw).is_dir():
            p = (curr.parent / raw).resolve()
        else:
            p = p.resolve()
    else:
        p = p.resolve()

    if not p.exists() or not p.is_dir():
        raise FileNotFoundError(f"Directory not found: {new_root}")

    _ACTIVE_WORKSPACE_ROOT = p
    logger.info("Workspace root set to: %s", p)
    return p


def resolve_safe_path(rel_or_abs_path: str, root_dir: Path | None = None) -> Path:
    """Resolve a path safely within the allowed root directory, preventing path traversal."""
    root = (root_dir or get_workspace_root()).resolve()
    clean = (rel_or_abs_path or "").strip()
    
    # If empty or "." return root
    if not clean or clean in (".", "/"):
        return root

    p = Path(clean)
    if p.is_absolute():
        target = p.resolve()
    else:
        # Strip leading slashes to evaluate relative to root
        clean_relative = clean.lstrip("/\\")
        # If model passed a relative path starting with root folder name (e.g. "aether/test.txt" when in "aether")
        # and that folder doesn't genuinely exist as a subdirectory inside root, strip the root prefix.
        norm_parts = Path(clean_relative).parts
        if norm_parts and norm_parts[0].lower() == root.name.lower() and not (root / norm_parts[0]).is_dir():
            clean_relative = str(Path(*norm_parts[1:])) if len(norm_parts) > 1 else ""
        target = (root / clean_relative).resolve()

    # Safety check: target must be inside root
    try:
        target.relative_to(root)
    except ValueError:
        raise PermissionError(f"Access denied: path '{rel_or_abs_path}' escapes workspace root '{root}'.")

    return target


def detect_language(path: Path) -> str:
    """Detect programming language for syntax highlighting."""
    ext = path.suffix.lstrip(".").lower()
    return LANG_MAP.get(ext, "plaintext")


def is_binary_file(path: Path) -> bool:
    """Check if file appears to be binary by inspecting first 1024 bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            if b"\x00" in chunk:
                return True
        return False
    except Exception:
        return True


def list_files_tree(
    path: str = ".",
    max_depth: int = 3,
    include_hidden: bool = False,
    root_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate a hierarchical tree of files and directories within the workspace."""
    root = (root_dir or get_workspace_root()).resolve()
    target = resolve_safe_path(path, root_dir=root)

    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    def _build_tree(curr: Path, depth: int) -> dict[str, Any] | None:
        try:
            is_dir = curr.is_dir()
            st = curr.stat()
            mtime_iso = datetime.fromtimestamp(st.st_mtime).astimezone().isoformat()
        except (OSError, FileNotFoundError):
            return None

        rel = str(curr.relative_to(root)).replace("\\", "/")
        if rel == ".":
            rel = ""

        node: dict[str, Any] = {
            "name": curr.name or root.name,
            "path": rel,
            "type": "directory" if is_dir else "file",
            "modified": mtime_iso,
        }

        if not is_dir:
            node["size"] = st.st_size
            node["extension"] = curr.suffix.lstrip(".").lower()
            node["language"] = detect_language(curr)
            return node

        # Directory: recurse if within max_depth
        children: list[dict[str, Any]] = []
        if depth < max_depth:
            try:
                entries = sorted(curr.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                for entry in entries:
                    if not include_hidden and entry.name.startswith("."):
                        if entry.name not in (".env", ".gitignore"):
                            continue
                    if (
                        entry.name in DEFAULT_EXCLUDED_DIRS
                        or entry.name in DEFAULT_EXCLUDED_FILES
                        or entry.name.endswith((".db-shm", ".db-wal", ".db-journal", ".egg-info"))
                        or entry.name in ("build", "dist")
                    ):
                        continue

                    child = _build_tree(entry, depth + 1)
                    if child is not None:
                        children.append(child)
            except (PermissionError, OSError):
                pass
        node["children"] = children
        return node

    tree = _build_tree(target, 0)
    if tree is None:
        raise FileNotFoundError(f"Path does not exist or cannot be accessed: {path}")
    return tree


def format_tree_for_agent(tree: dict[str, Any], max_items: int = 100) -> str:
    """Format a hierarchical directory tree into a clean, compact text summary for the AI agent."""
    root_name = tree.get("name", "workspace")
    lines = [f"Workspace Root: '{root_name}'"]
    count = 0

    def _format_node(node: dict[str, Any], depth: int) -> None:
        nonlocal count
        if count >= max_items:
            return
        prefix = "  " * depth
        node_type = node.get("type")
        node_name = node.get("name", "")
        if depth > 0:
            count += 1
            if node_type == "directory":
                lines.append(f"{prefix}[DIR]  {node_name}/")
            else:
                size = node.get("size", 0)
                size_str = f" ({size:,} B)" if size < 1024 else f" ({size/1024:.1f} KB)"
                lines.append(f"{prefix}[FILE] {node_name}{size_str}")

        children = node.get("children", [])
        for child in children:
            if count >= max_items:
                break
            _format_node(child, depth + 1)

    _format_node(tree, 0)
    if count >= max_items:
        lines.append(f"  ... (and additional files/folders within the workspace)")
    lines.append(f"\nTotal items listed: {count}")
    return "\n".join(lines)


def read_file_content(path: str, max_bytes: int = 2_000_000, root_dir: Path | None = None) -> dict[str, Any]:
    """Read file content safely, detecting encoding and syntax language."""
    target = resolve_safe_path(path, root_dir=root_dir)
    root = (root_dir or get_workspace_root()).resolve()

    if not target.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if target.is_dir():
        raise IsADirectoryError(f"Target is a directory: {path}")

    size = target.stat().st_size
    rel_path = str(target.relative_to(root)).replace("\\", "/")

    if is_binary_file(target):
        return {
            "path": rel_path,
            "name": target.name,
            "content": "",
            "size": size,
            "lines": 0,
            "language": "binary",
            "is_binary": True,
            "modified": datetime.fromtimestamp(target.stat().st_mtime).astimezone().isoformat(),
        }

    if size > max_bytes:
        raise ValueError(f"File size ({size} bytes) exceeds maximum limit ({max_bytes} bytes).")

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = target.read_text(encoding="latin-1", errors="replace")

    lines = len(content.splitlines()) or (1 if content else 0)
    return {
        "path": rel_path,
        "name": target.name,
        "content": content,
        "size": size,
        "lines": lines,
        "language": detect_language(target),
        "is_binary": False,
        "modified": datetime.fromtimestamp(target.stat().st_mtime).astimezone().isoformat(),
    }


def write_file_content(
    path: str,
    content: str,
    create_backup: bool = True,
    root_dir: Path | None = None,
) -> dict[str, Any]:
    """Write text content to a file, creating parent directories if needed."""
    target = resolve_safe_path(path, root_dir=root_dir)
    root = (root_dir or get_workspace_root()).resolve()

    target.parent.mkdir(parents=True, exist_ok=True)

    # Optional backup for existing files
    if create_backup and target.exists() and target.is_file():
        backup_dir = root / "data" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"{target.name}_{timestamp}.bak"
        try:
            shutil.copy2(target, backup_file)
        except Exception as e:
            logger.debug("Failed to create backup: %s", e)

    target.write_text(content, encoding="utf-8")
    size = target.stat().st_size
    rel_path = str(target.relative_to(root)).replace("\\", "/")

    return {
        "status": "success",
        "path": rel_path,
        "size": size,
        "modified": datetime.fromtimestamp(target.stat().st_mtime).astimezone().isoformat(),
    }


def create_file_or_folder(path: str, is_directory: bool = False, root_dir: Path | None = None) -> dict[str, Any]:
    """Create a new file or directory."""
    target = resolve_safe_path(path, root_dir=root_dir)
    root = (root_dir or get_workspace_root()).resolve()

    if target.exists():
        raise FileExistsError(f"Entry already exists: {path}")

    if is_directory:
        target.mkdir(parents=True, exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()

    rel_path = str(target.relative_to(root)).replace("\\", "/")
    return {
        "status": "success",
        "path": rel_path,
        "type": "directory" if is_directory else "file",
    }


def delete_file_or_folder(path: str, permanent: bool = False, root_dir: Path | None = None) -> dict[str, Any]:
    """Delete a file or folder (defaults to moving to .trash for safety)."""
    target = resolve_safe_path(path, root_dir=root_dir)
    root = (root_dir or get_workspace_root()).resolve()

    if not target.exists():
        raise FileNotFoundError(f"Entry not found: {path}")

    if target == root:
        raise PermissionError("Cannot delete workspace root.")

    rel_path = str(target.relative_to(root)).replace("\\", "/")

    if permanent:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"status": "success", "path": rel_path, "action": "deleted_permanently"}

    # Move to trash
    trash_dir = root / "data" / "vault" / ".trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trash_target = trash_dir / f"{timestamp}_{target.name}"

    shutil.move(str(target), str(trash_target))
    return {"status": "success", "path": rel_path, "action": "moved_to_trash", "trash_path": str(trash_target)}


def move_or_rename(source: str, destination: str, root_dir: Path | None = None) -> dict[str, Any]:
    """Move or rename a file or folder safely within workspace."""
    src_target = resolve_safe_path(source, root_dir=root_dir)
    dst_target = resolve_safe_path(destination, root_dir=root_dir)
    root = (root_dir or get_workspace_root()).resolve()

    if not src_target.exists():
        raise FileNotFoundError(f"Source path not found: {source}")

    if dst_target.exists():
        raise FileExistsError(f"Destination path already exists: {destination}")

    dst_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_target), str(dst_target))

    return {
        "status": "success",
        "source": str(src_target.relative_to(root)).replace("\\", "/"),
        "destination": str(dst_target.relative_to(root)).replace("\\", "/"),
    }


def search_files(
    query: str,
    path: str = ".",
    extension: str | None = None,
    content_search: bool = False,
    limit: int = 50,
    root_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Search for files by name, extension, or grep inside content."""
    root = (root_dir or get_workspace_root()).resolve()
    target = resolve_safe_path(path, root_dir=root)
    query_lower = query.lower().strip()
    ext_clean = extension.lstrip(".").lower() if extension else None

    results: list[dict[str, Any]] = []

    if not target.exists() or not target.is_dir():
        return results

    for current_root, dirs, files in os.walk(target):
        # In-place filter out excluded directories
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS and not d.startswith(".")]

        for fname in files:
            if fname in DEFAULT_EXCLUDED_FILES or fname.startswith("."):
                continue

            fpath = Path(current_root) / fname
            f_ext = fpath.suffix.lstrip(".").lower()

            if ext_clean and f_ext != ext_clean:
                continue

            rel_str = str(fpath.relative_to(root)).replace("\\", "/")

            if not content_search:
                # Name matching
                if not query_lower or query_lower in fname.lower():
                    results.append({
                        "name": fname,
                        "path": rel_str,
                        "size": fpath.stat().st_size,
                        "extension": f_ext,
                        "language": detect_language(fpath),
                        "modified": datetime.fromtimestamp(fpath.stat().st_mtime).astimezone().isoformat(),
                    })
                    if len(results) >= limit:
                        return results
            else:
                # Content search (grep)
                if is_binary_file(fpath) or fpath.stat().st_size > 1_000_000:
                    continue

                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        for line_idx, line in enumerate(f, 1):
                            if query_lower in line.lower():
                                results.append({
                                    "name": fname,
                                    "path": rel_str,
                                    "line": line_idx,
                                    "content": line.strip()[:200],
                                    "extension": f_ext,
                                })
                                if len(results) >= limit:
                                    return results
                except Exception:
                    continue

    return results


def organize_directory(
    target_path: str,
    strategy: str = "by_type",
    root_dir: Path | None = None,
) -> dict[str, Any]:
    """Organize cluttered loose files in a folder into categorized subfolders."""
    root = (root_dir or get_workspace_root()).resolve()
    target = resolve_safe_path(target_path, root_dir=root)

    if not target.exists() or not target.is_dir():
        raise NotADirectoryError(f"Target folder does not exist: {target_path}")

    moved: list[dict[str, str]] = []

    # Get only direct files in target directory
    files = [f for f in target.iterdir() if f.is_file() and not f.name.startswith(".")]

    for file in files:
        ext = file.suffix.lower()
        folder_name = "Other"

        if strategy == "by_type":
            for cat_name, extensions in CATEGORY_MAP.items():
                if ext in extensions:
                    folder_name = cat_name
                    break
        elif strategy == "by_date":
            mtime = datetime.fromtimestamp(file.stat().st_mtime)
            folder_name = mtime.strftime("%Y-%m")

        dest_dir = target / folder_name
        dest_dir.mkdir(exist_ok=True)
        dest_file = dest_dir / file.name

        # If file already exists in dest, append index
        if dest_file.exists():
            stem = file.stem
            counter = 1
            while dest_file.exists():
                dest_file = dest_dir / f"{stem}_{counter}{file.suffix}"
                counter += 1

        shutil.move(str(file), str(dest_file))
        moved.append({
            "name": file.name,
            "from": str(file.relative_to(root)).replace("\\", "/"),
            "to": str(dest_file.relative_to(root)).replace("\\", "/"),
            "category": folder_name,
        })

    logger.info("Organized %d files in %s", len(moved), target)
    return {
        "status": "success",
        "folder": str(target.relative_to(root)).replace("\\", "/"),
        "strategy": strategy,
        "count": len(moved),
        "moved": moved,
    }


def open_picker_dialog(
    picker_type: str = "folder",
    initial_dir: str | None = None,
    title: str | None = None,
) -> str | None:
    """Open a native Windows file or folder picker dialog in the foreground.

    Returns the absolute path selected by the user, or None if cancelled.
    """
    initial = str(initial_dir or get_workspace_root())
    dialog_title = title or ("Select Folder" if picker_type == "folder" else "Select File")

    # 1. Primary Method: Dedicated Python Tkinter script with TopMost parent and AllowSetForegroundWindow
    script_path = Path(__file__).parent / "picker_dialog.py"
    if script_path.exists():
        try:
            cmd = [
                sys.executable,
                str(script_path),
                f"--type={picker_type}",
                f"--initial={initial}",
                f"--title={dialog_title}",
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            selected = proc.stdout.strip()
            if selected and os.path.exists(selected):
                return str(Path(selected).resolve())
            if proc.returncode == 0 and not selected:
                # User deliberately closed or cancelled dialog
                return None
        except subprocess.TimeoutExpired:
            logger.warning("Tkinter picker timed out.")
            return None
        except Exception as e:
            logger.warning("Tkinter picker script failed (%s). Falling back to PowerShell...", e)

    # 2. Secondary Method: Dedicated PowerShell script with TopMost owner Form
    ps_script_path = Path(__file__).parent / "picker_dialog.ps1"
    if ps_script_path.exists():
        try:
            cmd = [
                "powershell",
                "-STA",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps_script_path),
                "-Type",
                picker_type,
                "-Initial",
                initial,
                "-Title",
                dialog_title,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            selected = proc.stdout.strip()
            if selected and os.path.exists(selected):
                return str(Path(selected).resolve())
            return None
        except Exception as e:
            logger.error("PowerShell picker failed: %s", e)
            return None

    return None


def reveal_in_explorer(target_path: str) -> bool:
    """Reveal a file or directory in the native OS file explorer."""
    try:
        p = Path(target_path).resolve()
        if not p.exists():
            p = resolve_safe_path(target_path)
        if not p.exists():
            return False

        if os.name == "nt":
            if p.is_dir():
                subprocess.Popen(["explorer.exe", str(p)])
            else:
                subprocess.Popen(["explorer.exe", f"/select,{str(p)}"])
            return True
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, str(p if p.is_dir() else p.parent)])
            return True
    except Exception as e:
        logger.error("Failed to reveal in explorer: %s", e)
        return False


def parse_search_replace_blocks(patch_text: str) -> list[tuple[str, str]]:
    """Parse Aider-style search/replace blocks from input text.

    Format:
    <<<<<<< SEARCH
    [code snippet to match]
    =======
    [code snippet to substitute]
    >>>>>>> REPLACE
    """
    pattern = re.compile(
        r"<{5,9}\s*SEARCH[^\n]*\r?\n(.*?)\r?\n={5,9}[^\n]*\r?\n(.*?)(?:\r?\n)?>{5,9}\s*REPLACE",
        re.DOTALL | re.IGNORECASE,
    )
    blocks: list[tuple[str, str]] = []
    for match in pattern.finditer(patch_text):
        search_block = match.group(1)
        replace_block = match.group(2)
        blocks.append((search_block, replace_block))
    return blocks


def parse_unified_diff_blocks(diff_text: str) -> list[tuple[str, str]]:
    """Parse unified diff hunks (--- / +++ / @@) into search/replace blocks."""
    lines = diff_text.splitlines()
    blocks: list[tuple[str, str]] = []
    search_lines: list[str] = []
    replace_lines: list[str] = []
    in_hunk = False

    for line in lines:
        if line.startswith("@@"):
            if in_hunk and (search_lines or replace_lines):
                blocks.append(("\n".join(search_lines), "\n".join(replace_lines)))
                search_lines = []
                replace_lines = []
            in_hunk = True
            continue

        if not in_hunk:
            continue

        if line.startswith("-"):
            search_lines.append(line[1:])
        elif line.startswith("+"):
            replace_lines.append(line[1:])
        elif line.startswith(" "):
            search_lines.append(line[1:])
            replace_lines.append(line[1:])
        elif line.startswith("\\ No newline at end of file"):
            continue
        elif line.startswith("diff --git") or line.startswith("--- ") or line.startswith("+++ "):
            if search_lines or replace_lines:
                blocks.append(("\n".join(search_lines), "\n".join(replace_lines)))
                search_lines = []
                replace_lines = []
            in_hunk = False

    if search_lines or replace_lines:
        blocks.append(("\n".join(search_lines), "\n".join(replace_lines)))

    return blocks


def fuzzy_replace_block(content: str, search: str, replace: str) -> tuple[str, str]:
    """Replace a code block using 4 tiers of matching tolerance:
    1. Exact match.
    2. Line-ending normalization (CRLF / LF).
    3. Trailing-whitespace & blank-line tolerance.
    4. Indentation-tolerant matching with relative delta preservation.
    """
    if not search:
        raise ValueError("Search block cannot be empty.")

    is_crlf = "\r\n" in content

    # Tier 1: Exact string match
    if search in content:
        count = content.count(search)
        if count > 1:
            raise ValueError(
                f"Target snippet matches {count} times in file. Include more surrounding lines for a unique match."
            )
        return content.replace(search, replace, 1), "exact"

    # Tier 2: Line-ending normalization
    norm_content = content.replace("\r\n", "\n")
    norm_search = search.replace("\r\n", "\n")
    norm_replace = replace.replace("\r\n", "\n")

    if norm_search in norm_content:
        count = norm_content.count(norm_search)
        if count > 1:
            raise ValueError(
                f"Target snippet matches {count} times in file (normalized line endings). Include more surrounding lines."
            )
        new_norm = norm_content.replace(norm_search, norm_replace, 1)
        if is_crlf:
            new_norm = new_norm.replace("\n", "\r\n")
        return new_norm, "line_ending_normalized"

    # Tier 3: Trailing whitespace / blank line tolerance
    c_lines = norm_content.split("\n")
    s_lines = norm_search.split("\n")
    r_lines = norm_replace.split("\n")
    n_search = len(s_lines)

    c_stripped = [line.rstrip() for line in c_lines]
    s_stripped = [line.rstrip() for line in s_lines]

    matches_tier3: list[int] = []
    for i in range(len(c_lines) - n_search + 1):
        if c_stripped[i : i + n_search] == s_stripped:
            matches_tier3.append(i)

    if len(matches_tier3) == 1:
        idx = matches_tier3[0]
        new_lines = c_lines[:idx] + r_lines + c_lines[idx + n_search :]
        result = "\n".join(new_lines)
        if is_crlf:
            result = result.replace("\n", "\r\n")
        return result, "trailing_whitespace_stripped"
    elif len(matches_tier3) > 1:
        raise ValueError(
            f"Target snippet matches {len(matches_tier3)} times with trailing whitespace stripped. Include more surrounding lines."
        )

    # Tier 4: Indentation-tolerant matching with relative delta preservation
    s_lstripped = [line.lstrip() for line in s_lines]
    s_non_empty_indices = [idx for idx, line in enumerate(s_lines) if line.strip()]

    if s_non_empty_indices:
        matches_tier4: list[tuple[int, int]] = []
        for i in range(len(c_lines) - n_search + 1):
            window = c_lines[i : i + n_search]
            window_lstripped = [line.lstrip() for line in window]
            if window_lstripped == s_lstripped:
                deltas = []
                for idx in s_non_empty_indices:
                    c_indent = len(window[idx]) - len(window[idx].lstrip())
                    s_indent = len(s_lines[idx]) - len(s_lines[idx].lstrip())
                    deltas.append(c_indent - s_indent)
                if len(set(deltas)) == 1:
                    matches_tier4.append((i, deltas[0]))

        if len(matches_tier4) == 1:
            idx, delta = matches_tier4[0]
            adjusted_r_lines: list[str] = []
            for r_line in r_lines:
                if not r_line.strip():
                    adjusted_r_lines.append("")
                elif delta >= 0:
                    adjusted_r_lines.append((" " * delta) + r_line)
                else:
                    remove = min(abs(delta), len(r_line) - len(r_line.lstrip(" ")))
                    adjusted_r_lines.append(r_line[remove:])

            new_lines = c_lines[:idx] + adjusted_r_lines + c_lines[idx + n_search :]
            result = "\n".join(new_lines)
            if is_crlf:
                result = result.replace("\n", "\r\n")
            return result, "indentation_adjusted"
        elif len(matches_tier4) > 1:
            raise ValueError(
                f"Target snippet matches {len(matches_tier4)} times with adjusted indentation. Include more context."
            )

    raise ValueError(
        f"Target snippet not found in '{content[:100]}...'. Failed exact match, line-ending normalization, "
        f"whitespace-trimmed match, and indentation-tolerant match."
    )


def patch_file_content(
    path: str,
    target: str,
    replacement: str = "",
    root_dir: Path | None = None,
) -> dict[str, Any]:
    """Patch an existing file with search-replace blocks, unified diff, or fuzzy snippet matching."""
    target_path = resolve_safe_path(path, root_dir=root_dir)
    if not target_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if target_path.is_dir():
        raise IsADirectoryError(f"Target is a directory: {path}")

    content = target_path.read_text(encoding="utf-8", errors="replace")

    # 1. Check if target or replacement contains Aider-style search/replace blocks
    blocks = parse_search_replace_blocks(target)
    if not blocks and replacement:
        blocks = parse_search_replace_blocks(replacement)

    # 2. If no Aider blocks, check if target is a unified diff
    if not blocks and (target.startswith("---") or "\n@@ " in target):
        blocks = parse_unified_diff_blocks(target)

    # 3. Fallback: treat (target, replacement) as a single search/replace block
    if not blocks:
        blocks = [(target, replacement)]

    # Save backup before patching
    backup_path = target_path.with_suffix(target_path.suffix + ".bak")
    try:
        shutil.copy2(target_path, backup_path)
    except Exception:
        pass

    new_content = content
    tiers_used: list[str] = []
    for search_blk, replace_blk in blocks:
        try:
            new_content, tier = fuzzy_replace_block(new_content, search_blk, replace_blk)
            tiers_used.append(tier)
        except ValueError as e:
            raise ValueError(f"Failed to patch '{path}': {e}") from e

    target_path.write_text(new_content, encoding="utf-8")

    return {
        "status": "success",
        "path": path,
        "blocks_applied": len(blocks),
        "tiers_used": tiers_used,
        "message": f"Successfully patched '{path}' ({len(blocks)} block(s) applied via {', '.join(set(tiers_used))}).",
        "bytes_written": len(new_content.encode("utf-8")),
    }


# Permitted binary and command names for workspace shell execution
ALLOWED_BINARIES = {
    "python", "python.exe", "python3", "python3.exe",
    "pytest", "pytest.exe",
    "ruff", "mypy", "black", "flake8", "isort", "pylint",
    "pip", "pip.exe", "pip3", "pip3.exe", "uv", "poetry",
    "node", "node.exe", "npm", "npm.cmd", "npx", "npx.cmd", "yarn", "pnpm", "bun", "deno", "tsc",
    "cargo", "rustc", "go", "dotnet",
    "git", "git.exe",
    "dir", "ls", "type", "cat", "echo", "findstr", "grep", "head", "tail",
}

# Dangerous patterns strictly rejected
BLOCKED_PATTERNS = [
    "format ",
    "diskpart",
    "shutdown",
    "rmdir /s /q c:",
    "del /f /s /q c:",
    ":(){ :|:& };:",
    "-enc",
    "-encodedcommand",
    "cmd.exe /c net",
    "certutil",
    "vssadmin",
    "regedit",
    "reg add",
    "reg delete",
    "runas",
    "sudo",
]


def validate_terminal_command(command: str, root_dir: Path) -> tuple[bool, str]:
    """Validate that a terminal command adheres to the execution allowlist and workspace sandbox."""
    raw = command.strip()
    if not raw:
        return False, "Empty command rejected."

    cmd_lower = raw.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in cmd_lower:
            return False, f"Command rejected by safety gate: destructive pattern '{pattern}' detected."

    if "$(" in raw or "`" in raw or "${" in raw:
        return False, "Command substitution operators ($(), ` `, ${}) are rejected for safety."

    try:
        sub_cmds = re.split(r"(?:\s*&&\s*|\s*\|\|\s*|\s*;\s*)", raw)
    except Exception as e:
        return False, f"Failed to parse command structure: {e}"

    resolved_root = root_dir.resolve()

    for sub in sub_cmds:
        sub = sub.strip()
        if not sub:
            continue

        pipe_parts = [p.strip() for p in sub.split("|")]
        for part in pipe_parts:
            if not part:
                continue

            try:
                tokens = shlex.split(part, posix=(os.name != "nt"))
            except Exception:
                tokens = part.split()

            if not tokens:
                continue

            bin_raw = tokens[0].strip().strip('"').strip("'")
            bin_name = Path(bin_raw).name.lower()
            bin_base = bin_name
            for ext in (".exe", ".cmd", ".bat", ".ps1"):
                if bin_base.endswith(ext):
                    bin_base = bin_base[:-len(ext)]
                    break

            if bin_name not in ALLOWED_BINARIES and bin_base not in ALLOWED_BINARIES:
                return (
                    False,
                    f"Command '{bin_raw}' rejected: binary not in execution allowlist. "
                    f"Allowed tools: {', '.join(sorted(ALLOWED_BINARIES))}",
                )

            for token in tokens[1:]:
                clean_tok = token.strip().strip('"').strip("'")
                if clean_tok.startswith("-"):
                    continue

                if clean_tok.startswith(">") or clean_tok.startswith(">>"):
                    target_file = clean_tok.lstrip(">").strip()
                    if target_file:
                        try:
                            t_path = (resolved_root / target_file).resolve()
                            if not t_path.is_relative_to(resolved_root):
                                return False, f"Output redirection outside workspace rejected: '{target_file}'"
                        except Exception:
                            return False, f"Invalid redirection path: '{target_file}'"
                    continue

                if "/" in clean_tok or "\\" in clean_tok or clean_tok.startswith("."):
                    try:
                        p = Path(clean_tok)
                        if p.is_absolute():
                            resolved_p = p.resolve()
                            if not resolved_p.is_relative_to(resolved_root):
                                return False, f"Path outside workspace rejected: '{clean_tok}'"
                        elif ".." in clean_tok:
                            resolved_p = (resolved_root / clean_tok).resolve()
                            if not resolved_p.is_relative_to(resolved_root):
                                return False, f"Directory traversal escaping workspace rejected: '{clean_tok}'"
                    except Exception:
                        pass

    return True, "OK"


def execute_terminal_command(
    command: str,
    timeout_seconds: int = 45,
    root_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute a terminal or shell command safely within the user workspace (e.g. pytest, python script.py, git status)."""
    root = (root_dir or get_workspace_root()).resolve()

    is_valid, reason = validate_terminal_command(command, root)
    if not is_valid:
        return {
            "status": "error",
            "message": f"Command rejected by sandbox allowlist: {reason}",
        }

    env = os.environ.copy()
    venv_scripts = root / ".venv" / "Scripts"
    venv_bin = root / ".venv" / "bin"
    if venv_scripts.exists():
        env["PATH"] = f"{str(venv_scripts)};{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(root / ".venv")
    elif venv_bin.exists():
        env["PATH"] = f"{str(venv_bin)}:{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(root / ".venv")

    env["PYTHONPATH"] = str(root)
    env["PYTHONUNBUFFERED"] = "1"

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(root),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "status": "success",
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-8000:] if len(proc.stdout) > 8000 else proc.stdout,
            "stderr": proc.stderr[-4000:] if len(proc.stderr) > 4000 else proc.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": f"Command timed out after {timeout_seconds} seconds.",
        }
    except Exception as e:
        return {"status": "error", "message": f"Execution failed: {e}"}


