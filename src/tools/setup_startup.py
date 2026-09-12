"""Tool to configure, verify, and simulate Windows Startup for Aether Morning Briefings."""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.daemon.briefing import BriefingService
from src.storage.db import DatabaseManager

console = Console()


def get_startup_folder() -> Path:
    """Return the Windows User Startup folder path."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = str(Path.home() / "AppData" / "Roaming")
    startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup_dir.mkdir(parents=True, exist_ok=True)
    return startup_dir


def get_shortcut_path() -> Path:
    """Return path to the Aether Startup shortcut."""
    return get_startup_folder() / "AetherMorningBriefing.lnk"


def get_bat_launcher_path() -> Path:
    """Return resolved path to launch_briefing.bat."""
    root = Path(__file__).resolve().parent.parent.parent
    return (root / "scripts" / "launch_briefing.bat").resolve()


def get_vbs_launcher_path() -> Path:
    """Return resolved path to launch_briefing.vbs."""
    root = Path(__file__).resolve().parent.parent.parent
    return (root / "scripts" / "launch_briefing.vbs").resolve()


def install_startup_shortcut() -> bool:
    """Create a Windows .lnk shortcut in the user's Startup folder."""
    vbs_launcher = get_vbs_launcher_path()
    bat_launcher = get_bat_launcher_path()
    if not bat_launcher.exists():
        console.print(f"[red][ERROR][/red] Launcher script not found at {bat_launcher}")
        return False

    shortcut = get_shortcut_path()
    root_dir = bat_launcher.parent.parent

    # Use native PowerShell WScript.Shell to create the .lnk cleanly
    # Point TargetPath to wscript.exe with vbs_launcher so no command prompt terminal pops up
    if vbs_launcher.exists():
        ps_cmd = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{str(shortcut)}'); "
            f"$s.TargetPath = 'wscript.exe'; "
            f"$s.Arguments = '\"\"{str(vbs_launcher)}\"\"'; "
            f"$s.WorkingDirectory = '{str(root_dir)}'; "
            f"$s.WindowStyle = 7; "
            f"$s.Description = 'Project Aether Autonomous Daily Morning Briefing & Web App'; "
            f"$s.Save()"
        )
        display_target = f"wscript.exe {vbs_launcher}"
    else:
        ps_cmd = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{str(shortcut)}'); "
            f"$s.TargetPath = '{str(bat_launcher)}'; "
            f"$s.WorkingDirectory = '{str(root_dir)}'; "
            f"$s.WindowStyle = 7; "
            f"$s.Description = 'Project Aether Autonomous Daily Morning Briefing & Web App'; "
            f"$s.Save()"
        )
        display_target = str(bat_launcher)

    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=True,
        )
        if shortcut.exists():
            console.print(
                Panel(
                    f"[bold green][OK] Successfully configured Aether Startup Task![/bold green]\n\n"
                    f"Shortcut created: [cyan]{shortcut}[/cyan]\n"
                    f"Target launcher:  [cyan]{display_target}[/cyan]\n\n"
                    "[bold white]How this works:[/bold white]\n"
                    "1. Every time you open or start your laptop, Windows executes this launcher silently in the background.\n"
                    "2. It checks if you already received today's briefing.\n"
                    "   - [bold green]First time today[/bold green]: Prepares your morning briefing and automatically startups the Aether Web App in desktop mode.\n"
                    "   - [dim]Subsequent boots today[/dim]: Silently exits in 10ms with zero interruption.\n"
                    "3. You can toggle or inspect this anytime in [bold]Task Manager -> Startup Apps[/bold].",
                    title="Windows Startup Setup",
                    border_style="green",
                )
            )
            return True
        else:
            console.print(f"[red][ERROR][/red] Shortcut was not created: {res.stderr}")
            return False
    except Exception as e:
        console.print(f"[red][ERROR][/red] Failed to install startup shortcut: {e}")
        return False


def uninstall_startup_shortcut() -> bool:
    """Remove the Windows Startup shortcut."""
    shortcut = get_shortcut_path()
    if shortcut.exists():
        try:
            shortcut.unlink()
            console.print(f"[green][OK][/green] Removed startup shortcut: [cyan]{shortcut}[/cyan]")
            return True
        except Exception as e:
            console.print(f"[red][ERROR][/red] Failed to remove shortcut: {e}")
            return False
    else:
        console.print("[dim]Startup shortcut is not installed.[/dim]")
        return True


def show_status() -> None:
    """Display current startup task and briefing delivery status."""
    shortcut = get_shortcut_path()
    launcher = get_bat_launcher_path()
    db = DatabaseManager()
    service = BriefingService(db=db)

    now = datetime.now().astimezone()
    today_str = now.strftime("%Y-%m-%d")
    last_run_date = db.get_state("last_briefing_date", "Never")
    last_run_ts = db.get_state("last_briefing_timestamp", "N/A")
    is_delivered = service.is_briefing_completed_for_today(today_str)
    missed_days = service.detect_missed_days(target_date=now)

    table = Table(title="Aether Startup & Morning Briefing Status")
    table.add_column("Property", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim")

    is_installed = shortcut.exists()
    status_str = "[green]Enabled (Active)[/green]" if is_installed else "[yellow]Not Installed[/yellow]"
    table.add_row("Windows Auto-Startup", status_str, str(shortcut) if is_installed else "Run with --install")

    delivered_str = "[green]Delivered Today[/green]" if is_delivered else "[yellow]Pending (Will run on next boot)[/yellow]"
    table.add_row("Today's Briefing", delivered_str, f"Date: {today_str}")

    table.add_row("Last Briefing Date", str(last_run_date), f"Timestamp: {last_run_ts}")

    if missed_days:
        missed_str = f"[yellow]{len(missed_days)} day(s) missed ({missed_days[0]} to {missed_days[-1]})[/yellow]"
    else:
        missed_str = "[green]0 days (Up to date)[/green]"
    table.add_row("Catch-Up Gap", missed_str, "Detects gaps >1 day between boots")

    console.print(table)


def simulate_missed_days(days: int = 2) -> None:
    """Simulate having missed N days by setting last_briefing_date back in SQLite."""
    db = DatabaseManager()
    simulated_date = (datetime.now().astimezone() - timedelta(days=days + 1)).strftime("%Y-%m-%d")
    db.set_state("last_briefing_date", simulated_date)
    console.print(
        f"[yellow][*][/yellow] Simulated last briefing date set to: [cyan]{simulated_date}[/cyan] "
        f"([bold red]{days} missed day(s)[/bold red])."
    )
    console.print("Run this to test the catch-up briefing right now:")
    console.print("  [bold green].venv\\Scripts\\python -m src.daemon.main --on-startup[/bold green]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure Aether Windows Startup Briefing")
    parser.add_argument("--install", action="store_true", help="Install Windows startup shortcut")
    parser.add_argument("--uninstall", action="store_true", help="Remove Windows startup shortcut")
    parser.add_argument("--status", action="store_true", help="Show current startup and briefing status")
    parser.add_argument(
        "--simulate-missed",
        type=int,
        metavar="DAYS",
        help="Simulate a missed gap of N days to test catch-up briefing",
    )
    args = parser.parse_args()

    if args.install:
        install_startup_shortcut()
        return

    if args.uninstall:
        uninstall_startup_shortcut()
        return

    if args.simulate_missed is not None:
        simulate_missed_days(args.simulate_missed)
        return

    # Default to status if no other action provided
    show_status()


if __name__ == "__main__":
    main()
