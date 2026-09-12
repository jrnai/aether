"""Unit tests for src/servers/files_server.py."""
from datetime import datetime
from pathlib import Path
import pytest

from src.servers.files_server import (
    create_file_or_folder,
    delete_file_or_folder,
    detect_language,
    list_files_tree,
    move_or_rename,
    organize_directory,
    read_file_content,
    resolve_safe_path,
    search_files,
    write_file_content,
)


@pytest.fixture
def test_workspace(tmp_path: Path) -> Path:
    """Create a temporary isolated workspace with sample code and files."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Create directory structure
    (ws / "src").mkdir()
    (ws / "docs").mkdir()
    (ws / "downloads").mkdir()

    # Create files
    (ws / "src" / "main.py").write_text("print('hello world')\nimport os\n", encoding="utf-8")
    (ws / "src" / "utils.js").write_text("export function add(a, b) { return a + b; }\n", encoding="utf-8")
    (ws / "docs" / "readme.md").write_text("# Project Documentation\nWelcome to Aether.\n", encoding="utf-8")
    (ws / "config.yaml").write_text("version: '1.0'\nenv: test\n", encoding="utf-8")

    # Cluttered downloads folder
    (ws / "downloads" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    (ws / "downloads" / "script.py").write_text("# test script", encoding="utf-8")
    (ws / "downloads" / "photo.png").write_text("dummy png", encoding="utf-8")
    (ws / "downloads" / "archive.zip").write_text("dummy zip", encoding="utf-8")

    return ws


def test_resolve_safe_path_valid(test_workspace: Path) -> None:
    path = resolve_safe_path("src/main.py", root_dir=test_workspace)
    assert path == (test_workspace / "src" / "main.py").resolve()

    root_path = resolve_safe_path(".", root_dir=test_workspace)
    assert root_path == test_workspace.resolve()


def test_resolve_safe_path_traversal_blocked(test_workspace: Path) -> None:
    with pytest.raises(PermissionError):
        resolve_safe_path("../../outside.txt", root_dir=test_workspace)

    with pytest.raises(PermissionError):
        resolve_safe_path("../", root_dir=test_workspace)


def test_detect_language() -> None:
    assert detect_language(Path("test.py")) == "python"
    assert detect_language(Path("app.js")) == "javascript"
    assert detect_language(Path("index.html")) == "html"
    assert detect_language(Path("notes.md")) == "markdown"
    assert detect_language(Path("unknown.xyz")) == "plaintext"


def test_list_files_tree(test_workspace: Path) -> None:
    tree = list_files_tree(".", max_depth=2, root_dir=test_workspace)
    assert tree["type"] == "directory"
    assert "children" in tree

    child_names = [c["name"] for c in tree["children"]]
    assert "src" in child_names
    assert "docs" in child_names
    assert "config.yaml" in child_names


def test_read_and_write_file_content(test_workspace: Path) -> None:
    # Read
    res = read_file_content("src/main.py", root_dir=test_workspace)
    assert res["language"] == "python"
    assert "print('hello world')" in res["content"]
    assert res["lines"] == 2

    # Write new content
    write_file_content("src/main.py", "print('updated')", create_backup=True, root_dir=test_workspace)
    updated = read_file_content("src/main.py", root_dir=test_workspace)
    assert updated["content"] == "print('updated')"

    # Check backup created
    backup_dir = test_workspace / "data" / "backups"
    assert backup_dir.exists()
    backups = list(backup_dir.glob("main.py_*.bak"))
    assert len(backups) >= 1


def test_create_and_delete_entry(test_workspace: Path) -> None:
    # Create file
    create_file_or_folder("src/new_mod.py", is_directory=False, root_dir=test_workspace)
    assert (test_workspace / "src" / "new_mod.py").exists()

    # Create folder
    create_file_or_folder("src/subfolder", is_directory=True, root_dir=test_workspace)
    assert (test_workspace / "src" / "subfolder").is_dir()

    # Delete to trash
    del_res = delete_file_or_folder("src/new_mod.py", permanent=False, root_dir=test_workspace)
    assert del_res["action"] == "moved_to_trash"
    assert not (test_workspace / "src" / "new_mod.py").exists()

    # Permanent delete
    perm_file = test_workspace / "temp.txt"
    perm_file.write_text("to be destroyed", encoding="utf-8")
    del_perm = delete_file_or_folder("temp.txt", permanent=True, root_dir=test_workspace)
    assert del_perm["action"] == "deleted_permanently"
    assert not perm_file.exists()


def test_move_or_rename(test_workspace: Path) -> None:
    move_or_rename("docs/readme.md", "docs/GUIDE.md", root_dir=test_workspace)
    assert not (test_workspace / "docs" / "readme.md").exists()
    assert (test_workspace / "docs" / "GUIDE.md").exists()


def test_search_files_by_name_and_content(test_workspace: Path) -> None:
    # By name
    name_results = search_files("main", root_dir=test_workspace)
    assert len(name_results) == 1
    assert name_results[0]["name"] == "main.py"

    # By extension
    js_results = search_files("", extension="js", root_dir=test_workspace)
    assert len(js_results) == 1
    assert js_results[0]["name"] == "utils.js"

    # Grep content
    grep_results = search_files("hello world", content_search=True, root_dir=test_workspace)
    assert len(grep_results) >= 1
    assert grep_results[0]["name"] == "main.py"
    assert grep_results[0]["line"] == 1


def test_organize_directory_by_type(test_workspace: Path) -> None:
    res = organize_directory("downloads", strategy="by_type", root_dir=test_workspace)
    assert res["status"] == "success"
    assert res["count"] == 4

    dl_dir = test_workspace / "downloads"
    assert (dl_dir / "Documents" / "report.pdf").exists()
    assert (dl_dir / "Code" / "script.py").exists()
    assert (dl_dir / "Images" / "photo.png").exists()
    assert (dl_dir / "Archives" / "archive.zip").exists()


def test_set_and_get_workspace_root(test_workspace: Path) -> None:
    from src.servers.files_server import get_workspace_root, set_workspace_root
    original = get_workspace_root()
    try:
        new_ws = set_workspace_root(test_workspace)
        assert new_ws == test_workspace.resolve()
        assert get_workspace_root() == test_workspace.resolve()
    finally:
        set_workspace_root(original)


def test_reveal_in_explorer(test_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.servers.files_server import reveal_in_explorer
    launched_cmds = []
    monkeypatch.setattr("subprocess.Popen", lambda cmd: launched_cmds.append(cmd))

    success = reveal_in_explorer(str(test_workspace / "src" / "main.py"))
    assert success is True
    assert len(launched_cmds) == 1


def test_patch_file_content(test_workspace: Path) -> None:
    from src.servers.files_server import patch_file_content
    py_file = "src/main.py"
    res = patch_file_content(py_file, "print('hello world')", "print('hello Aether')", root_dir=test_workspace)
    assert res["status"] == "success"

    updated = (test_workspace / "src" / "main.py").read_text(encoding="utf-8")
    assert "print('hello Aether')" in updated
    assert "print('hello world')" not in updated

    # Check backup file exists
    assert (test_workspace / "src" / "main.py.bak").exists()


def test_execute_terminal_command(test_workspace: Path) -> None:
    from src.servers.files_server import execute_terminal_command
    res = execute_terminal_command("python -c \"print('test terminal')\"", root_dir=test_workspace)
    assert res["status"] == "success"
    assert "test terminal" in res["stdout"]

    # Test safety blacklist
    bad_res = execute_terminal_command("format c:", root_dir=test_workspace)
    assert bad_res["status"] == "error"
    assert "rejected" in bad_res["message"].lower()


def test_set_workspace_root_smart_resolution(tmp_path: Path) -> None:
    from src.servers.files_server import set_workspace_root, get_workspace_root

    # Setup parent / child structure: Projects / aether
    projects_dir = tmp_path / "Projects"
    projects_dir.mkdir()
    aether_dir = projects_dir / "aether"
    aether_dir.mkdir()

    # Set to aether first
    set_workspace_root(aether_dir)
    assert get_workspace_root() == aether_dir.resolve()

    # Switch using parent folder name 'Projects'
    switched = set_workspace_root("Projects")
    assert switched == projects_dir.resolve()
    assert get_workspace_root() == projects_dir.resolve()

    # Switch back using relative 'aether'
    switched_back = set_workspace_root("aether")
    assert switched_back == aether_dir.resolve()


