"""Main CLI entrypoint for Project Aether."""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from src.agent.guardrails import SafetyGuard
from src.agent.loop import AgentLoop
from src.client.ollama_client import OllamaClient
from src.config import get_config
from src.mcp_bridge.manager import MCPBridgeManager
from src.storage.db import DatabaseManager, make_sqlite_audit_logger

console = Console()


def print_banner() -> None:
    console.print(
        Panel(
            "[bold cyan]PROJECT AETHER[/bold cyan]\n"
            "[italic dim]Modular, Privacy-First Local Desktop Automation Agent[/italic dim]\n"
            "Powered by Local Ollama (Qwen 2.5) + Model Context Protocol (MCP) + SQLite",
            border_style="cyan",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Project Aether - Privacy-First Local Desktop Automation")
    parser.add_argument("--config", "-c", default=None, help="Path to custom config.yaml")
    parser.add_argument("--model", "-m", default=None, help="Override default LLM model name")
    parser.add_argument("--web", "-w", "--portal", "--dashboard", dest="web", action="store_true", help="Launch the local web dashboard / portal server")
    parser.add_argument("--open", "-o", action="store_true", help="Automatically open browser when starting portal")
    parser.add_argument("--host", default="127.0.0.1", help="Web dashboard host (default: 127.0.0.1)")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Web dashboard port (default: 8000)")
    parser.add_argument("--voice", action="store_true", help="Enable hands-free voice activation")
    args = parser.parse_args()

    # Load unified configuration with CLI overrides
    cli_overrides = {}
    if args.model:
        cli_overrides["llm"] = {"model": args.model}
    if args.voice:
        cli_overrides["voice"] = {"enabled": True}

    cfg = get_config(config_path=args.config, cli_overrides=cli_overrides)

    print_banner()

    if args.web:
        from src.web.server import run_web_server
        run_web_server(host=args.host, port=args.port, open_browser=args.open)
        return

    # 1. Connect to Ollama
    client = OllamaClient(default_model=cfg.llm.model)
    if not client.is_connected():
        console.print(f"[bold red]Error:[/bold red] Cannot connect to local Ollama daemon at {cfg.llm.base_url}.")
        console.print("Please start Ollama using [bold green]`ollama serve`[/bold green] and try again.")
        sys.exit(1)

    available_models = client.list_models()
    chosen_model = cfg.llm.model if cfg.llm.model in available_models else (available_models[0] if available_models else cfg.llm.model)
    console.print(f"[green][OK][/green] Connected to local Ollama [dim](Model: {chosen_model})[/dim]")

    # 2. Initialize Database & Session
    db = DatabaseManager(db_path=cfg.storage.database_path)
    session_id = db.create_session(title="Interactive CLI Session")
    audit_logger = make_sqlite_audit_logger(db, session_id=session_id)
    console.print(f"[green][OK][/green] Initialized persistent SQLite database [dim]({db.db_path.name}, session={session_id})[/dim]")

    # 3. Initialize Safety Guard & Agent Loop
    guard = SafetyGuard(audit_logger=audit_logger)
    loop = AgentLoop(model=chosen_model, client=client, guard=guard)

    # 4. Initialize MCP Bridge
    console.print("[yellow][*][/yellow] Launching MCP tool servers over stdio...")
    manager = MCPBridgeManager(config_path="config/mcp_servers.json")

    with manager:
        manager.register_all_tools(loop)
        registered_tools = list(manager.tools_metadata.keys())
        console.print(f"[green][OK][/green] Discovered and bound {len(registered_tools)} MCP tools: [cyan]{', '.join(registered_tools)}[/cyan]")
        console.print("\n[dim]Type your command or query below. Mutating actions require confirmation. Type 'exit' to quit.[/dim]\n")

        while True:
            try:
                user_input = console.input("[bold blue]Aether > [/bold blue]").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit"):
                    console.print("[dim]Goodbye![/dim]")
                    break

                db.add_message(session_id=session_id, role="user", content=user_input)
                console.print("[dim cyan]Thinking...[/dim cyan]")
                response = loop.run_turn(user_input)
                db.add_message(session_id=session_id, role="assistant", content=response)

                console.print("\n")
                console.print(Markdown(response))
                console.print("\n")

            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Session terminated.[/dim]")
                break


if __name__ == "__main__":
    main()
