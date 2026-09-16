"""Main entrypoint for Project Aether Background Daemon."""
import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from src.daemon.briefing import BriefingService

console = Console()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aether.daemon")


def ensure_web_app_running(
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    root_dir: Path | None = None,
) -> bool:
    """Ensure that the Aether Web App is running and open the browser/window if requested."""
    from src.web.server import _is_aether_running, open_desktop_app_window

    url = f"http://{host}:{port}"
    if _is_aether_running(host, port):
        logger.info("Aether Web App is already serving at %s.", url)
        if open_browser:
            try:
                open_desktop_app_window(url, app_mode=True)
            except Exception as e:
                logger.warning("Could not open desktop app window: %s", e)
                import webbrowser
                webbrowser.open(url)
        return True

    logger.info("Starting Aether Web App at %s in background...", url)
    root = (root_dir or Path(__file__).resolve().parent.parent.parent).resolve()
    python_exe = sys.executable

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0)

    cmd = [python_exe, "main.py", "--portal"]
    if open_browser:
        cmd.append("--open")

    try:
        subprocess.Popen(
            cmd,
            cwd=str(root),
            creationflags=creation_flags,
            close_fds=(sys.platform != "win32"),
        )
        for _ in range(12):
            time.sleep(0.25)
            if _is_aether_running(host, port):
                logger.info("Aether Web App successfully started and ready at %s.", url)
                return True
        return True
    except Exception as e:
        logger.error("Failed to start Aether Web App: %s", e)
        return False


def print_daemon_banner() -> None:
    console.print(
        Panel(
            "[bold cyan]AETHER BACKGROUND DAEMON[/bold cyan]\n"
            "[italic dim]Autonomous Background Intelligence & Scheduled Morning Briefings[/italic dim]",
            border_style="cyan",
        )
    )


def run_continuous_schedule(target_hour: int = 7, target_minute: int = 30) -> None:
    """Run continuously, triggering the daily briefing at target_hour:target_minute every morning."""
    service = BriefingService()
    console.print(f"[green][OK][/green] Scheduled daily morning briefing at [bold yellow]{target_hour:02d}:{target_minute:02d}[/bold yellow] local time.")
    console.print("[dim]Daemon running. Press Ctrl+C to stop.[/dim]\n")

    last_run_date = None

    while True:
        try:
            now = datetime.now().astimezone()
            today_str = now.strftime("%Y-%m-%d")

            # Check if it's time to run
            is_trigger_time = (now.hour == target_hour and now.minute >= target_minute) or (now.hour > target_hour)

            if is_trigger_time and last_run_date != today_str:
                console.print(f"\n[bold yellow][*] [{now.strftime('%H:%M:%S')}] Triggering Morning Briefing for {today_str}...[/bold yellow]")
                briefing_text, note_path = service.run_briefing_cycle(target_date=now)
                last_run_date = today_str
                console.print(f"[bold green][OK] Briefing generated and saved to {note_path}[/bold green]\n")
                console.print(Markdown(briefing_text[:400] + "..."))
                console.print("\n[bold green][*] Launching Aether Web Dashboard with today's briefing...[/bold green]\n")
                ensure_web_app_running(open_browser=True)

            # Sleep 30 seconds before next check
            time.sleep(30)
        except (KeyboardInterrupt, SystemExit):
            console.print("\n[dim]Daemon stopped by operator.[/dim]")
            break
        except Exception as e:
            logger.error("Error during daemon iteration: %s", e)
            time.sleep(60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Aether Background Intelligence Daemon")
    parser.add_argument("--run-once", action="store_true", help="Execute the morning briefing immediately and exit")
    parser.add_argument("--on-startup", action="store_true", help="Run once on laptop startup only if not already delivered today")
    parser.add_argument("--force", action="store_true", help="Force briefing delivery even if already delivered today")
    parser.add_argument("--no-web", action="store_true", help="Do not automatically launch web app on startup")
    parser.add_argument("--web", action="store_true", help="Automatically launch web app on briefing completion")
    parser.add_argument("--schedule", type=str, default="07:30", help="Time of day to run briefing in HH:MM format (default: 07:30)")
    parser.add_argument("--voice", action="store_true", help="Launch local voice activation listener alongside daemon")
    args = parser.parse_args()

    service = BriefingService()
    now = datetime.now().astimezone()
    today_str = now.strftime("%Y-%m-%d")

    # 1. Handle --on-startup (Once-per-day laptop startup)
    if args.on_startup:
        if not args.force and service.is_briefing_completed_for_today(today_str):
            console.print(f"[dim]Aether morning briefing for today ({today_str}) has already been delivered. Exiting.[/dim]")
            return

        print_daemon_banner()
        missed = service.detect_missed_days(target_date=now)
        if missed:
            console.print(
                f"[bold yellow]Welcome back![/bold yellow] You missed [cyan]{len(missed)}[/cyan] day(s) "
                f"([dim]{missed[0]} to {missed[-1]}[/dim]). Preparing catch-up briefing...\n"
            )
        else:
            console.print(f"[yellow][*][/yellow] Preparing your first morning briefing of the day for [cyan]{today_str}[/cyan]...\n")

        try:
            briefing_text, note_path = service.run_briefing_cycle(target_date=now)
            console.print(Panel(Markdown(briefing_text), title=f"Morning Briefing: {today_str}", border_style="green"))
            console.print(f"\n[dim]Briefing archived to [cyan]{note_path}[/cyan][/dim]\n")

            # Automatically launch the web app unless suppressed
            if not args.no_web:
                console.print("[bold green][*] Automatically starting up Aether Web Dashboard...[/bold green]\n")
                ensure_web_app_running(open_browser=True)
                time.sleep(1.0)
                return

            # Keep window open for reading only if --no-web was explicitly requested
            prompt_text = "[bold cyan]Press [Enter] to dismiss or type 'chat' to talk with Aether: [/bold cyan]"
            user_choice = console.input(prompt_text).strip().lower()

            if user_choice in ("chat", "c", "talk", "open", "y"):
                console.print("\n[bold green]Launching Aether interactive session...[/bold green]\n")
                subprocess.run([sys.executable, "src/main.py"])
        except Exception as e:
            console.print(f"[bold red]Error generating startup briefing:[/bold red] {e}")
            if not args.no_web:
                time.sleep(3.0)
            else:
                console.input("\n[dim]Press Enter to close window...[/dim]")
        return

    print_daemon_banner()

    # 2. Handle --run-once
    if args.run_once:
        console.print("[yellow][*][/yellow] Generating immediate Morning Briefing...")
        try:
            briefing_text, note_path = service.run_briefing_cycle(target_date=now)
            console.print(f"\n[bold green][OK] Morning Briefing generated and saved to [cyan]{note_path}[/cyan]![/bold green]\n")
            console.print(Panel(Markdown(briefing_text), title=f"Morning Briefing: {today_str}", border_style="green"))
            if args.web:
                ensure_web_app_running(open_browser=True)
        except Exception as e:
            console.print(f"[bold red]Error generating briefing:[/bold red] {e}")
            sys.exit(1)
        return

    # 3. Handle continuous schedule
    try:
        parts = args.schedule.strip().split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        hour, minute = 7, 30

    if args.voice:
        try:
            from src.voice.service import get_voice_service
            voice_srv = get_voice_service()
            voice_srv.start()
            console.print(f"[green][OK][/green] Voice activation active [dim](Wake word: '{voice_srv.wake_word}')[/dim]")
        except Exception as e:
            console.print(f"[bold red]Failed to start voice listener:[/bold red] {e}")

    run_continuous_schedule(target_hour=hour, target_minute=minute)


if __name__ == "__main__":
    main()
