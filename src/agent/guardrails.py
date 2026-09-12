"""Safety guard and Human-in-the-Loop (HITL) approval interceptor."""
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger("aether.guardrails")


@dataclass
class ToolSafetyAction:
    """Record of a tool safety evaluation and outcome."""
    tool_name: str
    arguments: dict[str, Any]
    is_safe: bool
    requires_approval: bool
    user_approved: bool | None = None
    timestamp: datetime = field(default_factory=datetime.now)


DEFAULT_SAFE_TOOLS = {
    "search_web",
    "fetch_web_page",
    "calendar_list_events",
    "calendar_get_free_slots",
    "notes_list_todos",
    "notes_read_daily",
    "mail_fetch_unread",
    "get_email_details",
    "mail_list_emails",
    "files_list_directory",
    "files_read_file",
    "files_search_files",
    "files_set_workspace",
}


class SafetyGuard:
    """Enforces human-in-the-loop authorization on mutating tool operations."""

    def __init__(
        self,
        confirmation_callback: Callable[[str, dict[str, Any]], bool] | None = None,
        audit_logger: Callable[[ToolSafetyAction], None] | None = None,
    ) -> None:
        self.tool_registry: dict[str, bool] = {t: True for t in DEFAULT_SAFE_TOOLS}
        self.confirmation_callback = confirmation_callback or self._default_cli_confirm
        self.audit_logger = audit_logger

    def register_tool(self, tool_name: str, safe: bool = True) -> None:
        """Register a tool with its safety classification."""
        self.tool_registry[tool_name] = safe
        logger.debug("Registered tool %s (safe=%s)", tool_name, safe)

    def is_safe(self, tool_name: str) -> bool:
        """Check if tool is considered safe/read-only. Unknown tools default to safe=False."""
        return self.tool_registry.get(tool_name, False)

    def requires_approval(self, tool_name: str) -> bool:
        """Return True if tool requires explicit human approval before execution."""
        return not self.is_safe(tool_name)

    def check_and_authorize(self, tool_name: str, arguments: dict[str, Any]) -> tuple[bool, str | None]:
        """Evaluate a tool invocation.

        Returns:
            (authorized, cancellation_message)
            If authorized is True, cancellation_message is None.
            If authorized is False, cancellation_message contains synthetic response.
        """
        is_tool_safe = self.is_safe(tool_name)

        if is_tool_safe:
            action = ToolSafetyAction(
                tool_name=tool_name,
                arguments=arguments,
                is_safe=True,
                requires_approval=False,
                user_approved=None,
            )
            if self.audit_logger:
                self.audit_logger(action)
            return True, None

        # Mutating action requires confirmation
        action = ToolSafetyAction(
            tool_name=tool_name,
            arguments=arguments,
            is_safe=False,
            requires_approval=True,
        )

        try:
            approved = self.confirmation_callback(tool_name, arguments)
        except Exception as e:
            logger.error("Error during confirmation callback for %s: %s", tool_name, e)
            approved = False

        action.user_approved = approved
        if self.audit_logger:
            self.audit_logger(action)

        if approved:
            return True, None

        cancel_response = json.dumps({
            "status": "cancelled",
            "message": f"Action '{tool_name}' was cancelled by the human operator.",
            "tool": tool_name,
        })
        return False, cancel_response

    @staticmethod
    def _default_cli_confirm(tool_name: str, arguments: dict[str, Any]) -> bool:
        """Default interactive CLI confirmation prompt with formatted JSON arguments."""
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.syntax import Syntax

            console = Console()
            args_json = json.dumps(arguments, indent=2)
            syntax = Syntax(args_json, "json", theme="monokai", line_numbers=False)
            console.print("\n")
            console.print(
                Panel(
                    syntax,
                    title=f"[bold yellow]! AETHER SAFETY INTERCEPT: {tool_name}[/bold yellow]",
                    subtitle="[bold red]Action Requires Human Authorization[/bold red]",
                    border_style="yellow",
                )
            )
        except Exception:
            print(f"\n[AETHER SAFETY INTERCEPT] Tool: {tool_name}")
            print(f"Arguments:\n{json.dumps(arguments, indent=2)}")

        try:
            from rich.prompt import Confirm
            return Confirm.ask("[bold cyan]Authorize execution?[/bold cyan]", default=False)
        except Exception:
            choice = input("Authorize execution? [y/N]: ").strip().lower()
            return choice in ("y", "yes")
