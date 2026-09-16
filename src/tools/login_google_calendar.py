"""Interactive CLI helper to authenticate Google Calendar via OAuth 2.0 (100% Free)."""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.servers.google_calendar_client import SCOPES, GoogleCalendarManager

console = Console()


def print_setup_instructions() -> None:
    """Print step-by-step instructions to get free Google Calendar OAuth credentials."""
    console.print(
        Panel(
            "[bold cyan]GOOGLE CALENDAR OAUTH SETUP GUIDE (100% FREE)[/bold cyan]\n\n"
            "[bold white]Step 1: Go to Google Cloud Console[/bold white]\n"
            "  Open: [link=https://console.cloud.google.com/]https://console.cloud.google.com/[/link]\n"
            "  [dim](No credit card or billing account required for personal Google Calendar API)[/dim]\n\n"
            "[bold white]Step 2: Create a Free Project[/bold white]\n"
            "  Click on the project dropdown at the top -> [bold green]New Project[/bold green]\n"
            "  Name it: [cyan]Aether[/cyan] and click [bold green]Create[/bold green].\n\n"
            "[bold white]Step 3: Enable Google Calendar API[/bold white]\n"
            "  Go to [bold]APIs & Services[/bold] -> [bold]Library[/bold]\n"
            "  Search for [cyan]Google Calendar API[/cyan] -> Click [bold green]Enable[/bold green].\n\n"
            "[bold white]Step 4: Configure OAuth Consent Screen[/bold white]\n"
            "  Go to [bold]APIs & Services[/bold] -> [bold]OAuth consent screen[/bold]\n"
            "  User Type: [bold green]External[/bold green] -> App Name: [cyan]Aether[/cyan] -> Fill email -> Save.\n"
            "  Under [bold]Test Users[/bold], click [bold green]+ Add Users[/bold green] and add your Gmail: [cyan]naijunnrong@gmail.com[/cyan].\n\n"
            "[bold white]Step 5: Create Credentials[/bold white]\n"
            "  Go to [bold]APIs & Services[/bold] -> [bold]Credentials[/bold] -> [bold green]+ Create Credentials[/bold green] -> [bold cyan]OAuth client ID[/bold cyan]\n"
            "  Application type: [bold green]Desktop app[/bold green] -> Name: [cyan]Aether Desktop[/cyan] -> Create.\n"
            "  Click [bold]Download JSON[/bold] on the created client ID.\n\n"
            "[bold yellow]Final Step:[/bold yellow]\n"
            "  Save or rename the downloaded file to [bold green]credentials.json[/bold green] in this folder:\n"
            f"  [cyan]{Path('.').resolve() / 'credentials.json'}[/cyan]\n"
            "  Then run this command again:\n"
            "  [bold green].venv\\Scripts\\python -m src.tools.login_google_calendar[/bold green]",
            title="Google Calendar Setup",
            border_style="cyan",
        )
    )


def show_status(manager: GoogleCalendarManager) -> None:
    """Display current Google Calendar connection status and test event retrieval."""
    has_creds = manager.is_oauth_configured()
    is_logged_in = manager.is_logged_in()
    has_ical = bool(manager.ical_url)

    table = Table(title="Google Calendar Integration Status")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim")

    if has_ical:
        url = manager.ical_url
        if not (url.startswith("https://") or url.startswith("http://")):
            ical_status = "[red]Invalid URL Scheme (missing https://)[/red]"
        elif "/calendar/embed" in url:
            ical_status = "[red]Incorrect URL (Web Embed URL, not iCal)[/red]"
        elif "/public/basic.ics" in url or "/public/" in url:
            ical_status = "[yellow]Public Address (Returns 404 for private calendars)[/yellow]"
        elif not (url.endswith(".ics") or "/basic.ics" in url):
            ical_status = "[yellow]Warning (Missing .ics extension)[/yellow]"
        else:
            ical_status = "[bold green]ACTIVE (Live Sync)[/bold green]"
    else:
        ical_status = "[dim]Not Configured[/dim]"

    table.add_row("Private iCal Feed (Method 1)", ical_status, manager.ical_url or "GOOGLE_CALENDAR_ICAL_URL not set in .env")

    creds_status = "[green]Found[/green]" if has_creds else "[dim]Not needed (Only for Method 2: 2-Way writing)[/dim]"
    table.add_row("credentials.json (Method 2)", creds_status, str(manager.get_credentials_path()))

    if is_logged_in:
        auth_status = "[bold green]Connected (Valid Token)[/bold green]"
    elif manager.token_path.exists():
        auth_status = "[bold red]EXPIRED / REVOKED (Re-authentication required)[/bold red]"
    elif has_creds:
        auth_status = "[bold yellow]Not Logged In (Run script to authenticate)[/bold yellow]"
    else:
        auth_status = "[dim]Not configured (Only for Method 2: 2-Way writing)[/dim]"

    table.add_row("Google OAuth2 Token (Method 2)", auth_status, str(manager.token_path))

    console.print(table)

    # Check for specific iCal URL format mistakes and guide the user
    if has_ical:
        url = manager.ical_url
        if not (url.startswith("https://") or url.startswith("http://")):
            console.print(
                Panel(
                    f"[bold red]Format Error in GOOGLE_CALENDAR_ICAL_URL:[/bold red]\n"
                    f"The URL starts with [yellow]'{url[:7]}'[/yellow]. It looks like the leading [bold green]h[/bold green] is missing.\n"
                    f"Please edit [cyan].env[/cyan] to ensure it starts with [bold green]https://[/bold green].",
                    title="iCal URL Warning",
                    border_style="red",
                )
            )
        elif "/calendar/embed" in url:
            console.print(
                Panel(
                    "[bold red]Incorrect Calendar URL in .env:[/bold red]\n"
                    "You entered the [yellow]Web Embed URL[/yellow] (`.../calendar/embed?src=...`).\n"
                    "Google Calendar requires the [bold green]Secret address in iCal format[/bold green] (`.../basic.ics`).\n\n"
                    "[bold white]Where to find the Secret address in iCal format:[/bold white]\n"
                    "1. In Google Calendar Settings, look at the left sidebar.\n"
                    "2. Scroll down past 'General' and 'Add calendar' to [bold cyan]'Settings for my calendars'[/bold cyan].\n"
                    "3. Click on your calendar name or email ([bold]naijunnrong@gmail.com[/bold]).\n"
                    "4. Click [bold cyan]'Integrate calendar'[/bold cyan] in the menu.\n"
                    "5. Scroll down to [bold green]'Secret address in iCal format'[/bold green] and copy that URL.\n"
                    "   (It ends in [dim]/private-.../basic.ics[/dim])",
                    title="iCal Configuration Guide",
                    border_style="yellow",
                )
            )
        elif "/public/" in url:
            console.print(
                Panel(
                    "[bold yellow]You copied the 'Public address' instead of the 'Secret address':[/bold yellow]\n\n"
                    "Your URL currently contains [cyan]/public/basic.ics[/cyan]. Because personal Google Calendars are private, "
                    "Google returns [red]404 Not Found[/red] for this address.\n\n"
                    "[bold white]Quick Fix (Look right below it):[/bold white]\n"
                    "1. In that exact same [bold cyan]'Integrate calendar'[/bold cyan] section on Google Calendar, scroll down right below 'Public address in iCal format'.\n"
                    "2. You will see a box titled: [bold green]'Secret address in iCal format'[/bold green] with a warning message.\n"
                    "3. Click the [bold]copy button[/bold] next to that Secret URL (notice it contains [bold green]/private-[/bold green] instead of [bold yellow]/public/[/bold yellow]).\n"
                    "4. Paste it into [cyan].env[/cyan] line 35.",
                    title="Secret Address Required",
                    border_style="yellow",
                )
            )

    if is_logged_in or (has_ical and manager.ical_url.startswith("http") and "/embed" not in manager.ical_url and "/public/" not in manager.ical_url):
        source = "Google Calendar API (OAuth2)" if is_logged_in else "Private iCal Feed"
        console.print(f"\n[green][*][/green] Testing live event fetch via [cyan]{source}[/cyan]...")
        now = datetime.now().astimezone()
        try:
            events = manager.fetch_events(now, now + timedelta(days=7))
            if events:
                event_table = Table(title=f"Upcoming Events Next 7 Days ({len(events)} found)")
                event_table.add_column("Title", style="cyan")
                event_table.add_column("Start", style="green")
                event_table.add_column("End", style="yellow")
                event_table.add_column("Location", style="dim")
                for e in events[:5]:
                    event_table.add_row(e.get("title", "No Title"), str(e.get("start", "")), str(e.get("end", "")), str(e.get("location", "")))
                console.print(event_table)
            else:
                console.print("[bold green][OK][/bold green] Feed connected & verified! (No events scheduled in the next 7 days).")
                future = manager.fetch_events(now, now + timedelta(days=120))
                if future:
                    console.print(f"[cyan]Next upcoming event on your calendar:[/cyan] [bold]{future[0].get('title')}[/bold] on [green]{future[0].get('start')}[/green]")
        except Exception as err:
            console.print(f"[red][ERROR][/red] Failed to fetch events: {err}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Calendar Login & Status Tool")
    parser.add_argument("--status", action="store_true", help="Check current connection status")
    parser.add_argument("--logout", action="store_true", help="Log out and remove stored token")
    args = parser.parse_args()

    manager = GoogleCalendarManager()

    if args.logout:
        if manager.token_path.exists():
            manager.token_path.unlink()
            console.print(f"[green][OK][/green] Successfully logged out. Removed {manager.token_path}")
        else:
            console.print("[dim]Already logged out.[/dim]")
        return

    if args.status:
        show_status(manager)
        return

    if not manager.is_oauth_configured():
        print_setup_instructions()
        return

    # Run OAuth interactive flow
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds_file = manager.get_credentials_path()
        console.print(f"[*] Loading client secrets from [cyan]{creds_file.name}[/cyan]...")
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)

        console.print("[yellow][*][/yellow] Opening browser for Google Calendar consent...")
        console.print("[dim]Please sign in with your Google account and grant calendar access.[/dim]\n")
        creds = flow.run_local_server(port=0)

        with open(manager.token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

        console.print(f"[green][OK][/green] Successfully authenticated! Token saved to [cyan]{manager.token_path}[/cyan]\n")

        # Automatically sync any local events created while offline or before login
        try:
            from src.servers.calendar_server import load_events, sync_local_events_to_google
            unsynced = [e for e in load_events() if e.get("id", "").startswith("evt_")]
            if unsynced:
                console.print(f"[cyan][*][/cyan] Found {len(unsynced)} pending local event(s) scheduled offline. Syncing to Google Calendar...")
                sync_res = sync_local_events_to_google()
                console.print(f"[green][OK][/green] {sync_res.get('message')}\n")
        except Exception as sync_err:
            console.print(f"[yellow][!][/yellow] Post-login sync check skipped: {sync_err}\n")

        show_status(manager)
    except Exception as e:
        console.print(f"[red][ERROR][/red] Authentication flow failed: {e}")


if __name__ == "__main__":
    main()
