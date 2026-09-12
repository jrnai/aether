"""Diagnostic CLI tool to test email account connections (Gmail & Outlook)."""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.servers.email_client import MultiAccountEmailManager
from src.servers.outlook_graph_client import OutlookGraphManager

console = Console()


def main() -> None:
    console.print(
        Panel(
            "[bold cyan]AETHER EMAIL CONNECTION DIAGNOSTIC[/bold cyan]\n"
            "[italic dim]Testing Live Connectivity for Personal Gmail & School Outlook[/italic dim]",
            border_style="cyan",
        )
    )

    manager = MultiAccountEmailManager()
    accounts = manager.get_configured_accounts()
    outlook_manager = OutlookGraphManager()

    if not accounts and not outlook_manager.is_configured():
        console.print("[yellow][!] No live email accounts detected in environment or .env file.[/yellow]\n")
        console.print("To configure your accounts, update [bold cyan].env[/bold cyan] with:")
        console.print("""
[bold green]# Personal Gmail[/bold green]
GMAIL_USER=yourname@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

[bold green]# School Outlook[/bold green]
OUTLOOK_USER=yourname@e.ntu.edu.sg
""")
        sys.exit(0)

    table = Table(title="Configured Accounts", border_style="cyan")
    table.add_column("Account ID", style="bold")
    table.add_column("Label")
    table.add_column("Protocol / Server")
    table.add_column("Username")
    table.add_column("Status", style="bold")

    for acc in accounts:
        acc_id = acc["account_id"]

        # Handle School Outlook with Modern Auth
        if acc_id == "school":
            console.print(f"[*] Checking School Outlook ([cyan]{acc['username']}[/cyan])...")
            if outlook_manager.is_logged_in():
                emails = outlook_manager.fetch_unread_emails(limit=5)
                table.add_row("school", "School Outlook", "Microsoft Graph (OAuth2)", acc["username"], "[green][OK] Connected[/green]")
                console.print(f"  [green][OK] Connected via Modern Auth (OAuth2) - {len(emails)} unread messages found.[/green]")
            else:
                table.add_row("school", "School Outlook", "Microsoft Graph (OAuth2)", acc["username"], "[yellow][LOGIN NEEDED][/yellow]")
                console.print("  [yellow][!] Modern Auth required. Basic authentication is disabled by NTU.[/yellow]")
                console.print("  [cyan]-> Run: [bold green].venv\\Scripts\\python -m src.tools.login_outlook[/bold green] to sign in once.[/cyan]")
            continue

        # Standard IMAP (e.g. Gmail)
        console.print(f"[*] Testing connection for [cyan]{acc['label']}[/cyan] ({acc['username']})...")
        res = manager.test_connection(acc_id)

        if res["status"] == "success":
            table.add_row(acc_id, acc["label"], f"IMAP ({acc['server']})", acc["username"], "[green][OK] Connected[/green]")
            console.print(f"  [green][OK] {res['message']}[/green]")
        else:
            table.add_row(acc_id, acc["label"], f"IMAP ({acc['server']})", acc["username"], "[red][FAILED][/red]")
            console.print(f"  [red][ERROR] {res['message']}[/red]")

    console.print("\n")
    console.print(table)


if __name__ == "__main__":
    main()
