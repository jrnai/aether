"""Interactive Device Code login tool for Microsoft 365 / School Outlook."""
import sys
import webbrowser

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel

from src.servers.outlook_graph_client import OutlookGraphManager

console = Console()


def main() -> None:
    console.print(
        Panel(
            "[bold cyan]AETHER MICROSOFT 365 / OUTLOOK LOGIN[/bold cyan]\n"
            "[italic dim]Authenticate School Outlook (NTU) via Microsoft Device Login[/italic dim]",
            border_style="cyan",
        )
    )

    manager = OutlookGraphManager()
    if not manager.is_configured():
        console.print("[red][ERROR] OUTLOOK_USER is not set in your .env file.[/red]")
        console.print("Please add [cyan]OUTLOOK_USER=your_email@e.ntu.edu.sg[/cyan] to .env first.")
        sys.exit(1)

    console.print(f"[*] Account target: [cyan]{manager.username}[/cyan]")
    console.print("[yellow][*][/yellow] Requesting Microsoft device authorization code...")

    try:
        flow = manager.initiate_device_code_flow()
    except Exception as e:
        console.print(f"[red][ERROR] Failed to initiate device flow: {e}[/red]")
        sys.exit(1)

    if "user_code" not in flow:
        console.print(f"[red][ERROR] Unexpected response from Microsoft: {flow}[/red]")
        sys.exit(1)

    code = flow["user_code"]
    url = flow.get("verification_uri", "https://microsoft.com/devicelogin")

    instructions = (
        f"[bold]To sign in to your School Outlook account:[/bold]\n\n"
        f"1. Open this link in your browser: [bold cyan underline]{url}[/bold cyan underline]\n"
        f"2. Enter this device code: [bold yellow]{code}[/bold yellow]\n"
        f"3. Sign in with [cyan]{manager.username}[/cyan] and approve with Microsoft Authenticator.\n\n"
        f"[dim]Waiting for authentication... (Press Ctrl+C to abort)[/dim]"
    )

    console.print("\n")
    console.print(Panel(instructions, title="[bold green]Microsoft Sign-In Required[/bold green]", border_style="green"))
    console.print("\n")

    # Optionally attempt to open browser automatically
    try:
        webbrowser.open(url)
    except Exception:
        pass

    result = manager.complete_device_code_flow(flow)

    if result["status"] == "success":
        console.print(f"\n[bold green][OK] {result['message']}[/bold green]")
        console.print(f"[green][OK][/green] Signed in as: [bold cyan]{result['username']}[/bold cyan]")

        # Test fetching unread messages
        console.print("[yellow][*][/yellow] Fetching unread emails from your School Inbox...")
        emails = manager.fetch_unread_emails(limit=5)
        console.print(f"[bold green][OK] Discovered {len(emails)} unread messages in your NTU Outlook inbox![/bold green]\n")

        for e in emails:
            console.print(f"  • [bold]{e['sender']}[/bold]: {e['subject']}")
    else:
        console.print(f"\n[bold red][FAILED] {result['message']}[/bold red]")


if __name__ == "__main__":
    main()
