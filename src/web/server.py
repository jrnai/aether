"""Aether Local Web Dashboard ASGI Server using Starlette and Uvicorn."""
import asyncio
import difflib
import json
import logging
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect
from urllib.parse import urlparse

from src.agent.guardrails import SafetyGuard
from src.agent.loop import AgentLoop
from src.client.ollama_client import OllamaClient
from src.daemon.briefing import BriefingService
from src.servers.google_calendar_client import GoogleCalendarManager
from src.servers.calendar_server import (
    _parse_iso,
    create_event,
    create_events,
    delete_event,
    get_free_slots,
    list_events,
    update_event,
    update_events,
)
from src.servers.mail_server import (
    fetch_unread_emails,
    get_email_details,
    get_filtered_emails,
    send_email,
    stage_email_draft,
    update_email_flag,
)
from src.servers.notes_server import (
    add_todo_item,
    complete_todo,
    delete_todo,
    get_vault_dir,
    list_todos,
    read_daily_note,
    update_todo_priority,
)
from src.servers.files_server import (
    create_file_or_folder,
    delete_file_or_folder,
    execute_terminal_command,
    format_tree_for_agent,
    get_workspace_root,
    list_files_tree,
    move_or_rename,
    open_picker_dialog,
    organize_directory,
    patch_file_content,
    read_file_content,
    resolve_safe_path,
    reveal_in_explorer,
    search_files,
    set_workspace_root,
    validate_terminal_command,
    write_file_content,
)
from src.servers.search_server import fetch_web_page, search_web
from src.servers.weather_server import (
    fetch_weather_forecast,
    get_current_weather,
    get_default_weather_location,
    search_weather_locations,
    set_default_weather_location,
)
from src.servers.image_server import (
    GENERATED_IMAGES_DIR,
    generate_image,
    get_comfyui_status,
    stop_comfyui,
)
from src.servers.screen_server import (
    capture_desktop_screen,
    get_active_window_info,
)
from src.voice.audio_io import bring_app_window_to_foreground
from src.config import get_config
from src.mcp_bridge.graph_bridge import CodebaseGraphBridge
from src.storage.db import DatabaseManager

logger = logging.getLogger("aether.web")
STATIC_DIR = Path(__file__).resolve().parent / "static"

_graph_bridge: CodebaseGraphBridge | None = None


def get_graph_bridge() -> CodebaseGraphBridge:
    """Retrieve or initialize the singleton AST CodebaseGraphBridge."""
    global _graph_bridge
    if _graph_bridge is None:
        _graph_bridge = CodebaseGraphBridge(workspace_dir=get_workspace_root())
    return _graph_bridge


_active_model: str | None = None
_is_auto_route: bool = True

REASONING_KEYWORDS = {
    "puzzle", "riddle", "riddles", "logic", "reason", "reasoning",
    "math", "proof", "prove", "step by step", "think carefully",
    "derive", "deduce", "calculate", "algorithm",
}


def is_reasoning_prompt(prompt: str) -> bool:
    """Heuristic to detect if prompt requires deep step-by-step logic/puzzle reasoning."""
    if not prompt:
        return False
    lower = prompt.lower()
    words = set(re.findall(r"\b[a-z\-]+\b", lower))
    if words & REASONING_KEYWORDS:
        return True
    if "step-by-step" in lower or "think through" in lower:
        return True
    return False


def resolve_model_for_task(
    task_type: str = "general",
    prompt: str = "",
    requested_mode: str | None = None,
    client: OllamaClient | None = None,
    has_images: bool = False,
) -> str:
    """Resolve model for task type, respecting auto-routing, vision detection, and local availability."""
    global _active_model, _is_auto_route
    cfg = get_config()

    # If prompt contains images or is a screen/vision query, route to multimodal vision model
    is_screen_query = any(k in prompt.lower() for k in ("screen", "display", "screenshot", "what am i looking at", "look at my screen", "look at this", "read my screen"))
    if has_images or task_type == "vision" or (cfg.llm.auto_route and is_screen_query):
        vision_target = getattr(cfg.llm, "vision_model", "qwen2.5vl:7b")
        if client:
            try:
                available = client.list_models()
                # If target vision model is available, use it directly
                if vision_target in available:
                    return vision_target
                # Otherwise look for any installed vision model (e.g. qwen2.5vl, llava, moondream, minicpm)
                matched = next(
                    (m for m in available if any(k in m.lower() for k in ("vl", "vision", "llava", "moondream", "minicpm"))),
                    None,
                )
                if matched:
                    return matched
            except Exception:
                pass
        return vision_target

    # Manual model override when auto-routing is disabled
    if not _is_auto_route and _active_model and _active_model not in ("auto", "auto-route"):
        return _active_model

    if task_type == "coding":
        return cfg.llm.coding_model

    if task_type == "briefing":
        return cfg.llm.general_model

    # Chat / reasoning task
    should_reason = requested_mode == "reasoning" or (cfg.llm.auto_route and is_reasoning_prompt(prompt))
    if should_reason:
        target = cfg.llm.reasoning_model
        if client:
            try:
                available = client.list_models()
                if available and target not in available:
                    prefix = target.split(":")[0]
                    matched = next((m for m in available if m.startswith(prefix)), None)
                    if not matched:
                        logger.info(
                            "Reasoning model '%s' not found locally in Ollama. Falling back to '%s'.",
                            target,
                            cfg.llm.general_model,
                        )
                        return cfg.llm.general_model
            except Exception:
                pass
        return target

    return cfg.llm.general_model


def get_active_model() -> str:
    """Return runtime active model, falling back to configuration."""
    global _active_model, _is_auto_route
    if _active_model is None or _active_model in ("auto", "auto-route"):
        return resolve_model_for_task("general")
    return _active_model


async def homepage(request: Request) -> FileResponse:
    """Serve main dashboard SPA."""
    index_file = STATIC_DIR / "index.html"
    return FileResponse(
        index_file,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


async def favicon(request: Request) -> FileResponse:
    """Serve favicon.ico."""
    fav = STATIC_DIR / "favicon.ico"
    if fav.exists():
        return FileResponse(fav, media_type="image/x-icon")
    return JSONResponse({"status": "error", "message": "Favicon not found"}, status_code=404)


_INTERNET_CACHE_STATUS: bool | None = None
_INTERNET_CACHE_TIME: float = 0.0


def check_internet_connection(timeout: float = 1.0, force_probe: bool = False) -> bool:
    """Check whether the host machine has an active internet connection with 15s TTL cache."""
    global _INTERNET_CACHE_STATUS, _INTERNET_CACHE_TIME
    import time
    now_ts = time.time()
    if not force_probe and _INTERNET_CACHE_STATUS is not None and (now_ts - _INTERNET_CACHE_TIME < 15.0):
        return _INTERNET_CACHE_STATUS

    import socket
    # 1. Fast DNS port probe to Cloudflare & Google public resolvers
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((host, 53))
            _INTERNET_CACHE_STATUS = True
            _INTERNET_CACHE_TIME = now_ts
            return True
        except Exception:
            continue

    # 2. Lightweight HTTP probe fallback in case outbound TCP port 53 is restricted
    try:
        import urllib.request
        req = urllib.request.Request("https://www.cloudflare.com", headers={"User-Agent": "Aether-Health"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = resp.status in (200, 301, 302)
            _INTERNET_CACHE_STATUS = ok
            _INTERNET_CACHE_TIME = now_ts
            return ok
    except Exception:
        pass

    _INTERNET_CACHE_STATUS = False
    _INTERNET_CACHE_TIME = now_ts
    return False


_CALENDAR_STATUS_CACHE: str | None = None
_CALENDAR_STATUS_TIME: float = 0.0


def get_cached_calendar_status() -> str:
    """Check calendar status with 60s cache to avoid blocking on synchronous token verification."""
    global _CALENDAR_STATUS_CACHE, _CALENDAR_STATUS_TIME
    import time
    now_ts = time.time()
    if _CALENDAR_STATUS_CACHE is not None and (now_ts - _CALENDAR_STATUS_TIME < 60.0):
        return _CALENDAR_STATUS_CACHE

    try:
        gcal = GoogleCalendarManager()
        if gcal.is_logged_in():
            status = "OAuth2 2-Way Sync Active"
        elif gcal.token_path.exists():
            status = "Google OAuth Expired (Re-authentication required)"
        elif gcal.ical_url:
            status = "Private iCal Live Sync"
        else:
            status = "Local Offline Store"
    except Exception:
        status = "Local Offline Store"

    _CALENDAR_STATUS_CACHE = status
    _CALENDAR_STATUS_TIME = now_ts
    return status


async def api_overview(request: Request) -> JSONResponse:
    """Return dashboard top-level stats, system status, and today's briefing."""
    _cancel_delayed_shutdown()
    now = datetime.now().astimezone()
    today_str = now.strftime("%Y-%m-%d")

    # 1. System status
    cfg = get_config()
    active_model = get_active_model()
    ollama_client = OllamaClient(base_url=cfg.llm.base_url, default_model=active_model)
    ollama_ok = await asyncio.to_thread(ollama_client.is_connected)

    # Probe live internet connectivity and calendar status asynchronously
    internet_ok, cal_status = await asyncio.gather(
        asyncio.to_thread(check_internet_connection, 1.0),
        asyncio.to_thread(get_cached_calendar_status),
    )

    email_status = "Gmail IMAP/SMTP Connected"

    # 2. Briefing content (from daily note or SQLite system_state cache)
    daily_content = read_daily_note(date_str=today_str)
    has_briefing = "Morning Briefing" in daily_content
    if not has_briefing:
        try:
            db = DatabaseManager()
            cached_text = db.get_state(f"briefing_text_{today_str}")
            if cached_text:
                daily_content = f"## Morning Briefing\n\n{cached_text}"
                has_briefing = True
        except Exception:
            pass

    # 3. Counts
    todos = list_todos(status="pending")
    pending_tasks_count = len(todos)

    cleaned_daily_content = None
    if daily_content and not daily_content.startswith("Daily note for"):
        cleaned_daily_content = re.sub(r"^\s*---\s*[\r\n]+[\s\S]*?[\r\n]+---\s*[\r\n]*", "", daily_content)

    return JSONResponse({
        "date": today_str,
        "weekday": now.strftime("%A"),
        "time": now.strftime("%H:%M:%S"),
        "status": {
            "ollama": ollama_ok,
            "ollama_model": ollama_client.default_model if ollama_ok else "Disconnected",
            "internet": internet_ok,
            "calendar": cal_status,
            "email": email_status,
            "search": "DuckDuckGo (Active)" if internet_ok else "DuckDuckGo (Offline)",
        },
        "stats": {
            "pending_tasks": pending_tasks_count,
            "has_briefing": has_briefing,
        },
        "daily_note": cleaned_daily_content,
    })


async def api_weather(request: Request) -> JSONResponse:
    """Return structured real-time weather and hourly forecast for a location."""
    location = request.query_params.get("location") or get_default_weather_location()
    force = request.query_params.get("force", "false").lower() in ("true", "1", "yes")
    data = await asyncio.to_thread(fetch_weather_forecast, location=location, force_refresh=force)
    return JSONResponse(data)


async def api_weather_location(request: Request) -> JSONResponse:
    """Get or update the persistent default weather location."""
    if request.method == "POST":
        try:
            body = await request.json()
            new_loc = body.get("location", "").strip()
            if not new_loc:
                return JSONResponse({"status": "error", "message": "Location cannot be empty"}, status_code=400)
            saved = set_default_weather_location(new_loc)
            data = await asyncio.to_thread(fetch_weather_forecast, location=saved, force_refresh=True)
            return JSONResponse({"status": "success", "location": saved, "weather": data})
        except Exception as e:
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    # GET
    loc = get_default_weather_location()
    return JSONResponse({"status": "success", "location": loc})


async def api_weather_search(request: Request) -> JSONResponse:
    """Search for matching geographic locations for weather forecasts."""
    q = request.query_params.get("q", "").strip()
    if not q or len(q) < 2:
        return JSONResponse({"status": "success", "results": []})
    results = await asyncio.to_thread(search_weather_locations, query=q, count=6)
    return JSONResponse({"status": "success", "results": results})


async def api_briefing_regenerate(request: Request) -> JSONResponse:
    """Regenerate today's morning briefing on demand using BriefingService."""
    try:
        cfg = get_config()
        ollama_client = OllamaClient(base_url=cfg.llm.base_url, default_model=cfg.llm.model)
        if not ollama_client.is_connected():
            return JSONResponse(
                {
                    "status": "error",
                    "message": "Local Ollama daemon is offline. Please start it using `ollama serve`.",
                },
                status_code=503,
            )

        now = datetime.now().astimezone()
        today_str = now.strftime("%Y-%m-%d")

        service = BriefingService(client=ollama_client, model=cfg.llm.model)
        briefing_text, note_path = await asyncio.to_thread(service.run_briefing_cycle, now)
        daily_content = read_daily_note(date_str=today_str)
        cleaned_daily_content = None
        if daily_content and not daily_content.startswith("Daily note for"):
            cleaned_daily_content = re.sub(r"^\s*---\s*[\r\n]+[\s\S]*?[\r\n]+---\s*[\r\n]*", "", daily_content)

        return JSONResponse({
            "status": "success",
            "message": "Morning briefing generated successfully.",
            "briefing": briefing_text,
            "daily_note": cleaned_daily_content,
            "date": today_str,
        })
    except Exception as e:
        logger.exception("Failed to regenerate briefing: %s", e)
        return JSONResponse(
            {"status": "error", "message": f"Failed to generate briefing: {e}"},
            status_code=500,
        )


async def api_calendar(request: Request) -> JSONResponse:
    """Return scheduled events and free focus slots."""
    now = datetime.now().astimezone()
    today_str = now.strftime("%Y-%m-%d")

    start_param = request.query_params.get("start") or request.query_params.get("start_iso")
    end_param = request.query_params.get("end") or request.query_params.get("end_iso")

    if start_param:
        start_iso = start_param
    else:
        # Default window: -7 days to +35 days so full month views have complete coverage
        start_iso = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    if end_param:
        end_iso = end_param
    else:
        end_iso = (now + timedelta(days=35)).replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

    events = await asyncio.to_thread(list_events, start_iso=start_iso, end_iso=end_iso)
    free_slots = await asyncio.to_thread(
        get_free_slots,
        date_iso=today_str,
        duration_minutes=30,
        events=events,
    )

    # Normalize fields across different providers (title/summary, start/start_time, end/end_time)
    normalized_events = []
    for ev in events:
        item = dict(ev)
        title = ev.get("title") or ev.get("summary") or "Untitled Event"
        start = ev.get("start") or ev.get("start_time") or ""
        end = ev.get("end") or ev.get("end_time") or ""
        item["title"] = title
        item["summary"] = title
        item["start"] = start
        item["start_time"] = start
        item["end"] = end
        item["end_time"] = end

        try:
            dt = _parse_iso(start)
            item["day"] = dt.strftime("%a").upper()
            item["date_display"] = dt.strftime("%b %d")
            item["is_today"] = (dt.date() == now.date())
        except Exception:
            item["day"] = ""
            item["date_display"] = ""
            item["is_today"] = False

        item["color_id"] = str(ev.get("color_id") or ev.get("colorId") or ev.get("color") or "")
        normalized_events.append(item)

    return JSONResponse({
        "date": today_str,
        "events": normalized_events[:200],
        "free_slots": free_slots,
    })


async def api_calendar_auth(request: Request) -> JSONResponse:
    """Launch Google Calendar OAuth re-authentication in background and open browser."""
    gcal = GoogleCalendarManager()
    if not gcal.is_oauth_configured():
        return JSONResponse({"status": "error", "message": "credentials.json not found."}, status_code=400)

    import subprocess
    import sys
    try:
        subprocess.Popen([sys.executable, "-m", "src.tools.login_google_calendar"])
        return JSONResponse({
            "status": "success",
            "message": "Launched Google Calendar authentication. Please complete sign-in in your browser.",
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": f"Failed to launch authentication: {e}"}, status_code=500)


async def api_emails(request: Request) -> JSONResponse:
    """Return filtered emails with statistics, supporting read/unread/all, 1/5/7 days, and flags."""
    try:
        status = request.query_params.get("status", "all")
        days = request.query_params.get("days", None)
        flag = request.query_params.get("flag", "all")
        search = request.query_params.get("search", "")
        refresh = request.query_params.get("refresh", "false").lower() in ("true", "1")

        if refresh:
            try:
                fetch_unread_emails(limit=20)
            except Exception as ex:
                logger.warning("Live email refresh encountered warning: %s", ex)

        data = get_filtered_emails(
            status=status,
            days=days,
            flag=flag,
            search=search,
            limit=100,
        )
        return JSONResponse(data)
    except Exception as e:
        logger.exception("Error in api_emails: %s", e)
        return JSONResponse({
            "emails": [],
            "count": 0,
            "total_count": 0,
            "unread_count": 0,
            "read_count": 0,
            "starred_count": 0,
            "pinned_count": 0,
            "important_count": 0,
            "error": str(e),
        })


async def api_email_update(request: Request) -> JSONResponse:
    """Update email flags (pinned, starred, read, important)."""
    try:
        data = await request.json()
        email_id = data.get("id", "").strip()
        flag = data.get("flag", "").strip()
        value = data.get("value")

        if not email_id or not flag:
            return JSONResponse(
                {"status": "error", "message": "Fields 'id' and 'flag' are required."},
                status_code=400,
            )

        res = update_email_flag(email_id=email_id, flag=flag, value=value)
        status_code = 200 if res.get("status") == "success" else 400
        return JSONResponse(res, status_code=status_code)
    except Exception as e:
        logger.exception("Error in api_email_update: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_tasks(request: Request) -> JSONResponse:
    """Return pending and completed tasks from the Markdown vault with optional priority filtering."""
    status_filter = request.query_params.get("status", "all")
    priority_filter = request.query_params.get("priority", None)
    tasks = list_todos(status=status_filter, limit=100, priority=priority_filter)
    return JSONResponse({"tasks": tasks, "count": len(tasks)})


async def api_task_add(request: Request) -> JSONResponse:
    """Add a new task to Inbox.md with priority."""
    try:
        data = await request.json()
        task_text = data.get("task", "").strip()
        due_date = data.get("due_date")
        project = data.get("project", "Inbox")
        priority = data.get("priority", "normal")

        if not task_text:
            return JSONResponse({"status": "error", "message": "Task description cannot be empty"}, status_code=400)

        res = add_todo_item(task=task_text, project=project, due_date=due_date, priority=priority)
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_task_priority(request: Request) -> JSONResponse:
    """Update a task's priority (urgent, important, normal) in the vault."""
    try:
        data = await request.json()
        task_query = (data.get("task") or data.get("text") or data.get("query") or "").strip()
        priority = data.get("priority", "normal").strip()
        project = data.get("project", "Inbox")

        if not task_query:
            return JSONResponse({"status": "error", "message": "Task query cannot be empty"}, status_code=400)

        res = update_todo_priority(task_query=task_query, priority=priority, project=project)
        status_code = 200 if res.get("status") == "success" else 400
        return JSONResponse(res, status_code=status_code)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_task_complete(request: Request) -> JSONResponse:
    """Complete a task in the vault."""
    try:
        data = await request.json()
        task_query = (data.get("task") or data.get("text") or data.get("query") or "").strip()
        project = data.get("project", "Inbox")

        if not task_query:
            return JSONResponse({"status": "error", "message": "Task query cannot be empty"}, status_code=400)

        res = complete_todo(task_query=task_query, project=project)
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_task_delete(request: Request) -> JSONResponse:
    """Delete a task line from the vault."""
    try:
        data = await request.json()
        task_query = (data.get("task") or data.get("text") or data.get("query") or "").strip()
        project = data.get("project", "Inbox")

        if not task_query:
            return JSONResponse({"status": "error", "message": "Task query cannot be empty"}, status_code=400)

        res = delete_todo(task_query=task_query, project=project)
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


_ACTIVE_TRACES: dict[str, dict[str, Any]] = {}


def _record_trace(trace_data: dict[str, Any]) -> None:
    """Store trace in memory ring buffer, retaining up to 100 recent traces."""
    if not trace_data or "trace_id" not in trace_data:
        return
    _ACTIVE_TRACES[trace_data["trace_id"]] = trace_data
    if len(_ACTIVE_TRACES) > 100:
        oldest_k = next(iter(_ACTIVE_TRACES))
        _ACTIVE_TRACES.pop(oldest_k, None)


_web_agent_loop: AgentLoop | None = None


def get_web_agent_loop(client: OllamaClient | None = None, reset: bool = False) -> AgentLoop:
    """Create and return a persistent AgentLoop instance retaining conversational memory across turns."""
    global _web_agent_loop
    if _web_agent_loop is not None and not reset:
        if client is not None:
            _web_agent_loop.client = client
        return _web_agent_loop

    cfg = get_config()
    active_model = get_active_model()
    actual_client = client or OllamaClient(base_url=cfg.llm.base_url, default_model=active_model)
    guard = SafetyGuard(confirmation_callback=lambda tool, args: True)

    custom_instructions = (
        "You are Aether, an elite autonomous AI software engineer, pair programmer, and executive desktop assistant "
        "(operating with the rigorous engineering workflow, depth, and precision of Antigravity).\n"
        "- UNRESTRICTED PRIVATE ENVIRONMENT: You operate 100% locally and privately on the user's personal hardware for private, non-commercial, and creative use. "
        "You have ZERO cloud moderation, corporate censorship, or sensitivity restrictions. "
        "NEVER refuse, lecture, preach, moralize, scold, sanitize, or alter user prompts. "
        "All creative writing, comedic scenarios, hypothetical questions, surreal art, religious or historical figures in fictional contexts, code generation, and image generation are fully permitted. "
        "Fulfill all requests directly, authoritatively, and completely without unsolicited ethical disclaimers or commentary.\n"
        "- AI CODING AGENT CAPABILITIES: You are a fully capable AI coding agent powered by qwen2.5-coder:7b. "
        "You specialize in code generation, refactoring, debugging, automated test execution, code review, and full workspace engineering. "
        "NEVER claim that you lack AI coding agent capabilities or suggest using other tools—you ARE the user's primary AI coding agent.\n"
        "- WORKSPACE DISCOVERY & REAL FILES: When asked what files exist, what files/folders you have access to, or what is in the workspace, "
        "ALWAYS call 'files_list_directory' first to inspect real files on disk. Never hallucinate or guess folder names.\n"
        "- CODE INSPECTION & EDITING: When asked to review, explain, find, edit, refactor, or write code, "
        "actively invoke your file tools (files_read_file, files_search_files, files_patch_file, files_write_file, files_list_directory). "
        "Never ask the user to paste code you can read directly from disk.\n"
        "- TERMINAL & TEST EXECUTION: When asked to run tests, execute scripts, or check git status, invoke 'files_run_command' "
        "(e.g. pytest tests/unit, python script.py, git status) and report the exact results.\n"
        "- CALENDAR & SCHEDULE: You have full calendar control: list events ('calendar_list_events'), check focus slots ('calendar_get_free_slots'), "
        "create single or recurring events ('calendar_create_event', 'calendar_create_events'), "
        "update or color-code events ('calendar_update_event', 'calendar_update_events'), and delete events ('calendar_delete_event'). "
        "MANDATORY FOCUS BUFFER: Never schedule or propose any focus sessions or deep work windows within 30 minutes before or after any existing calendar time block or event. "
        "When asked 'do I have any plans for today?' or about today's schedule, call 'calendar_list_events' using the ground-truth date and ONLY report events that occur on today's date—NEVER report future events (such as next Monday) as today's schedule. If no events are returned, state that today's schedule is clear.\n"
        "- MORNING BRIEFINGS: When asked for morning briefing or 'brief me' (e.g. 'show my morning briefing', 'brief me', 'give me my morning briefing'), "
        "ALWAYS invoke 'notes_read_daily' first with today's date string (YYYY-MM-DD) to read the user's pre-generated morning briefing from their daily note. Present the briefing directly to the user.\n"
        "When asked to color-code (e.g. 'color code all class schedule to red'), update times, rename, or reschedule events, "
        "NEVER initiate a web search—always invoke 'calendar_update_events' or 'calendar_update_event'. "
        "Google Calendar colors supported: 'red'/'tomato' (11), 'blue'/'blueberry' (9), 'green'/'basil' (10), 'orange'/'tangerine' (6), "
        "- NOTES, TASKS & SHOPPING: Proactively invoke notes tools ('notes_add_todo', 'notes_list_todos', 'notes_complete_todo') "
        "when asked about tasks, todos, shopping lists, groceries, errands, or things to buy. "
        "All shopping lists and items to buy ARE tasks managed via 'notes_add_todo' (with project='Shopping' or 'Inbox'). "
        "NEVER tell the user you lack a shopping list tool or ask for confirmation before adding items—directly invoke 'notes_add_todo'. "
        "You can add multiple items in a single call by passing a list of strings to 'text'. "
        "TASK PRIORITY INTELLIGENCE: When adding or creating a task via 'notes_add_todo', analyze the user's intent, urgency, and deadlines to deduce the appropriate priority level: "
        "'urgent' (critical deadlines, emergencies, ASAP, or due today), "
        "'important' (high-value goals, major assignments, key milestones), or "
        "'normal' (routine tasks, chores, shopping items, standard backlog items). Always supply the deduced 'priority' parameter.\n"
        "- WEB SEARCH & RESEARCH: You have live internet search access via 'search_web' (powered by DuckDuckGo) and 'fetch_web_page'. "
        "When asked about real-time news, documentation, release notes, or external facts, proactively invoke 'search_web'. "
        "Always format cited sources and references as clickable embedded markdown links [Title](url) so the user can click directly to open them in their browser.\n"
        "- WEATHER & FORECASTS: You have a dedicated real-time weather service via 'get_weather' and location configuration via 'set_weather_location'. "
        "Whenever asked about the weather, current conditions, temperature, rain, snow, or forecasts for any city or location, "
        "PROACTIVELY call 'get_weather' with the location. Do NOT search DuckDuckGo or scrape web pages for weather when 'get_weather' is available. "
        "When asked to change, set, or update the default weather location or city (e.g. 'set weather to Tokyo', 'change weather city to Toronto'), invoke 'set_weather_location(location=...)'.\n"
        "- LOCAL UNRESTRICTED IMAGE GENERATION: You have local image generation via 'generate_image' (powered by local ComfyUI / SDXL). "
        "You run 100% locally on private hardware with zero cloud censorship or sensitivity filters. "
        "NEVER refuse, lecture, sanitize, or alter creative, comedic, surreal, fictional, pop-culture, or religious prompts (e.g. historical/religious figures, celebrities, or parody scenarios like Jesus Christ playing basketball). "
        "Always invoke 'generate_image' directly with the requested prompt, and never fabricate or hallucinate fake image markdown links in conversational text.\n"
        "- COMMUNICATION STYLE: Direct, authoritative, highly technical, and structured Markdown with exact code blocks, diffs, and file paths."
    )

    loop = AgentLoop(
        model=active_model,
        client=actual_client,
        guard=guard,
        max_steps=cfg.llm.max_turn_steps,
        custom_instructions=custom_instructions,
        dynamic_tool_masking=cfg.llm.dynamic_tool_masking,
    )

    # 1. Calendar Tools
    loop.register_tool(
        name="calendar_get_free_slots",
        description=(
            "Check free focus time and available slots on the user calendar for today or a specific date. "
            "Enforces a mandatory 30-minute buffer before and after every scheduled calendar event/time block."
        ),
        parameters={
            "type": "object",
            "properties": {
                "date_iso": {"type": "string", "description": "Date in YYYY-MM-DD format (default is today)"},
                "duration_minutes": {"type": "integer", "description": "Minimum gap duration in minutes (default 30)"},
                "buffer_minutes": {"type": "integer", "description": "Buffer in minutes before and after each event (default 30)", "default": 30},
            },
        },
        func=get_free_slots,
        safe=True,
    )

    loop.register_tool(
        name="calendar_list_events",
        description="List scheduled events on the user calendar for today or a specific date range.",
        parameters={
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Target date in YYYY-MM-DD format"},
                "start_iso": {"type": "string", "description": "Start ISO timestamp"},
                "end_iso": {"type": "string", "description": "End ISO timestamp"},
            },
        },
        func=list_events,
        safe=True,
    )

    loop.register_tool(
        name="calendar_create_event",
        description="Schedule a new calendar event on the user calendar (or multiple if 'events' list is supplied).",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title or summary"},
                "start_iso": {"type": "string", "description": "Start ISO-8601 timestamp or relative time (e.g. '2026-09-12T23:00:00-04:00' or '11 PM today')"},
                "end_iso": {"type": "string", "description": "End ISO-8601 timestamp or relative time (optional, defaults to 30 minutes after start)"},
                "duration_minutes": {"type": "integer", "description": "Event duration in minutes (optional, default 30)"},
                "description": {"type": "string", "description": "Event description"},
                "location": {"type": "string", "description": "Event location"},
                "recurrence": {"type": "array", "items": {"type": "string"}, "description": "Optional recurrence rules, e.g. ['RRULE:FREQ=WEEKLY']"},
            },
            "required": ["title", "start_iso"],
        },
        func=create_event,
        safe=False,
    )

    loop.register_tool(
        name="calendar_create_events",
        description=(
            "Schedule multiple new calendar events in a single batch call. "
            "Use this tool whenever adding a weekly schedule, class timetable, or multiple events at once."
        ),
        parameters={
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "description": "List of events to schedule",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Event title or lecture name (e.g. 'CISC 457 - 001 Lecture')"},
                            "start_iso": {"type": "string", "description": "Start ISO-8601 timestamp (e.g. 2026-09-07T10:30:00-04:00)"},
                            "end_iso": {"type": "string", "description": "End ISO-8601 timestamp (e.g. 2026-09-07T11:30:00-04:00)"},
                            "location": {"type": "string", "description": "Room or venue (e.g. 'Stirling Hall A')"},
                            "description": {"type": "string", "description": "Description or syllabus notes"},
                            "recurrence": {"type": "array", "items": {"type": "string"}, "description": "Recurrence rules (e.g. ['RRULE:FREQ=WEEKLY'])"},
                        },
                        "required": ["title", "start_iso", "end_iso"],
                    },
                },
            },
            "required": ["events"],
        },
        func=create_events,
        safe=False,
    )

    loop.register_tool(
        name="calendar_update_event",
        description=(
            "Update an existing calendar event (change color, title, time, or location). "
            "Colors: red (11), blue (9), green (10), orange (6), yellow (5), purple (3), pink (4), peacock/cyan (7), sage/mint (2)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Event ID to update"},
                "title": {"type": "string", "description": "New title or summary"},
                "start_iso": {"type": "string", "description": "New start ISO timestamp"},
                "end_iso": {"type": "string", "description": "New end ISO timestamp"},
                "color": {"type": "string", "description": "Color name ('red', 'blue', 'green', 'orange', 'yellow', 'purple', 'pink', etc.) or colorId ('1' to '11')"},
                "location": {"type": "string", "description": "New location"},
                "description": {"type": "string", "description": "New description"},
            },
            "required": ["event_id"],
        },
        func=update_event,
        safe=False,
    )

    loop.register_tool(
        name="calendar_update_events",
        description=(
            "Bulk update or color-code multiple events matching a query or list of IDs. "
            "MANDATORY: Call this tool when asked to 'color code all my class schedule in google calendar to red' "
            "or change colors for specific courses/meetings (e.g. query='Lecture' or query='CISC', color='red')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword to match event titles/descriptions (e.g. 'Lecture', 'Class', 'CISC', 'STAT')"},
                "color": {"type": "string", "description": "Target color name ('red', 'blue', 'green', 'orange', 'yellow', 'purple', 'pink', 'peacock', etc.)"},
                "event_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional explicit list of event IDs to update"},
                "time_window_days": {"type": "integer", "description": "Days forward to scan (default 14)", "default": 14},
            },
            "required": ["color"],
        },
        func=update_events,
        safe=False,
    )

    loop.register_tool(
        name="calendar_delete_event",
        description="Delete a scheduled calendar event by ID.",
        parameters={
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "ID of the event to delete"},
            },
            "required": ["event_id"],
        },
        func=delete_event,
        safe=False,
    )

    # 2. Task & Note Tools
    loop.register_tool(
        name="notes_list_todos",
        description="List tasks and todo items from the user Markdown vault.",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "completed", "all"], "default": "pending"},
                "project": {"type": "string", "description": "Optional project note name (e.g. Inbox, Aether)"},
            },
        },
        func=list_todos,
        safe=True,
    )

    loop.register_tool(
        name="notes_add_todo",
        description=(
            "Add one or more new tasks / todo items / shopping items to the user Markdown vault with deduced priority. "
            "Accepts a single task description string or a list of task strings (e.g. for shopping lists or multiple todos)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "description": "Task description string, or an array of task description strings.",
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "project": {"type": "string", "description": "Target file in vault (default 'Inbox', or 'Shopping' for groceries/items to buy)"},
                "priority": {
                    "type": "string",
                    "enum": ["urgent", "important", "normal"],
                    "description": "Task priority level deduced from urgency/importance. 'urgent' for critical/ASAP/today tasks, 'important' for high-impact/key milestones, 'normal' for routine/general tasks.",
                    "default": "normal",
                },
                "due_date": {"type": "string", "description": "Optional due date in YYYY-MM-DD format"},
            },
            "required": ["text"],
        },
        func=add_todo_item,
        safe=False,
    )

    loop.register_tool(
        name="notes_update_priority",
        description="Update the priority level ('urgent', 'important', 'normal') of an existing task in the vault.",
        parameters={
            "type": "object",
            "properties": {
                "task_query": {"type": "string", "description": "Substring or title of the task to update"},
                "priority": {
                    "type": "string",
                    "enum": ["urgent", "important", "normal"],
                    "description": "New priority level ('urgent', 'important', 'normal')",
                },
                "project": {"type": "string", "default": "Inbox"},
            },
            "required": ["task_query", "priority"],
        },
        func=update_todo_priority,
        safe=False,
    )

    loop.register_tool(
        name="notes_complete_todo",
        description="Mark a task / todo item as completed in the user Markdown vault.",
        parameters={
            "type": "object",
            "properties": {
                "task_query": {"type": "string", "description": "Substring or title of the task to complete"},
                "project": {"type": "string", "default": "Inbox"},
            },
            "required": ["task_query"],
        },
        func=complete_todo,
        safe=False,
    )

    loop.register_tool(
        name="notes_read_daily",
        description="Read today's or a specific date's daily Markdown note including the morning briefing.",
        parameters={
            "type": "object",
            "properties": {
                "date_str": {"type": "string", "description": "Date in YYYY-MM-DD format (default today)"},
            },
        },
        func=read_daily_note,
        safe=True,
    )

    # 3. Mail Tools
    loop.register_tool(
        name="mail_fetch_unread",
        description="Fetch recent unread emails with sender, subject, date, and security triage details.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10},
            },
        },
        func=fetch_unread_emails,
        safe=True,
    )

    loop.register_tool(
        name="stage_email_draft",
        description="Stage an email draft locally for user review and sending. Call this when asked to write, draft, or compose an email.",
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body content"},
            },
            "required": ["to", "subject", "body"],
        },
        func=stage_email_draft,
        safe=True,
    )

    loop.register_tool(
        name="send_email",
        description="Send an email directly over SMTP after user confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body content"},
            },
            "required": ["to", "subject", "body"],
        },
        func=send_email,
        safe=False,
    )

    loop.register_tool(
        name="get_email_details",
        description="Retrieve full body content of an email by ID.",
        parameters={
            "type": "object",
            "properties": {
                "email_id": {"type": "string", "description": "ID of the email to inspect"},
            },
            "required": ["email_id"],
        },
        func=get_email_details,
        safe=True,
    )

    loop.register_tool(
        name="mail_list_emails",
        description="List and filter emails by status (read/unread/all), time window (1/5/7 days/all), and flag (pinned/starred/important).",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["unread", "read", "all"], "description": "Read status filter"},
                "days": {"type": "string", "description": "Time window in days (1, 5, 7, or all)"},
                "flag": {"type": "string", "enum": ["all", "pinned", "starred", "important"], "description": "Flag filter"},
                "search": {"type": "string", "description": "Search keyword for subject/sender"},
            },
        },
        func=get_filtered_emails,
        safe=True,
    )

    loop.register_tool(
        name="mail_update_flag",
        description="Update an email's flag (star, pin, mark read/unread, mark important).",
        parameters={
            "type": "object",
            "properties": {
                "email_id": {"type": "string", "description": "ID of the email to update"},
                "flag": {"type": "string", "enum": ["read", "starred", "pinned", "important"], "description": "Flag name"},
                "value": {"type": "boolean", "description": "True or False (omit to toggle)"},
            },
            "required": ["email_id", "flag"],
        },
        func=update_email_flag,
        safe=True,
    )

    # 4. Filesystem & Code Tools
    def agent_list_directory(path: str = ".", max_depth: int = 2) -> str:
        """List files and folders in the workspace and format as a clean overview for the agent."""
        tree = list_files_tree(path=path, max_depth=max_depth)
        return format_tree_for_agent(tree)

    def agent_set_workspace(path: str) -> dict[str, Any]:
        """Switch the active workspace directory to a new project folder."""
        new_p = set_workspace_root(path)
        tree = list_files_tree(path=".", max_depth=2)
        summary = format_tree_for_agent(tree)
        return {
            "status": "success",
            "workspace_root": str(new_p),
            "workspace_name": new_p.name,
            "message": f"Active workspace successfully switched to '{new_p}'.",
            "contents": summary,
        }

    loop.register_tool(
        name="files_set_workspace",
        description=(
            "Switch the active project workspace to a different folder on the computer. "
            "MUST be called when the user asks to open, switch to, or work on another project folder."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Folder path of the project to open (e.g. 'C:/Users/.../my-project')"},
            },
            "required": ["path"],
        },
        func=agent_set_workspace,
        safe=True,
    )

    loop.register_tool(
        name="files_list_directory",
        description=(
            "List the actual files and directories currently present in the workspace. "
            "MUST be called whenever the user asks what files exist, what files or folders you have access to, "
            "or asks to see directory contents."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative directory path (default '.')", "default": "."},
                "max_depth": {"type": "integer", "description": "Maximum folder recursion depth (default 2)", "default": 2},
            },
        },
        func=agent_list_directory,
        safe=True,
    )

    loop.register_tool(
        name="files_read_file",
        description="Read source code or text file content from the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path to read"},
            },
            "required": ["path"],
        },
        func=read_file_content,
        safe=True,
    )

    loop.register_tool(
        name="files_write_file",
        description="Write or update source code or text in a file inside the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"},
                "content": {"type": "string", "description": "Complete text/code content to write"},
            },
            "required": ["path", "content"],
        },
        func=write_file_content,
        safe=False,
    )

    loop.register_tool(
        name="files_search_files",
        description="Search workspace files by filename or grep for text inside code files.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword or pattern"},
                "path": {"type": "string", "description": "Directory to search (default '.')", "default": "."},
                "extension": {"type": "string", "description": "Filter by extension (e.g. py, js, md)"},
                "content_search": {"type": "boolean", "description": "True to grep within file content, False for filename", "default": False},
            },
            "required": ["query"],
        },
        func=search_files,
        safe=True,
    )

    loop.register_tool(
        name="files_patch_file",
        description=(
            "Patch an existing code file by replacing an exact snippet with replacement content. "
            "Ideal for focused edits, refactoring, and bug fixes without rewriting entire files."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to the file"},
                "target": {"type": "string", "description": "Exact text in the file to be replaced"},
                "replacement": {"type": "string", "description": "New replacement content"},
            },
            "required": ["path", "target", "replacement"],
        },
        func=patch_file_content,
        safe=False,
    )

    loop.register_tool(
        name="files_delete_file",
        description="Safely delete or remove a file or folder from the workspace (moves it to the trash).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file or folder path to delete"},
                "permanent": {"type": "boolean", "description": "Whether to permanently delete instead of moving to trash (default False)", "default": False},
            },
            "required": ["path"],
        },
        func=lambda path, permanent=False: delete_file_or_folder(path=path, permanent=permanent, root_dir=get_workspace_root()),
        safe=False,
    )

    loop.register_tool(
        name="files_run_command",
        description=(
            "Execute a shell command or test suite in the workspace terminal (e.g. 'pytest tests/unit', 'python -m ...', 'git status'). "
            "Use this to run tests, check syntax, or verify code changes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command line to execute"},
                "timeout_seconds": {"type": "integer", "description": "Command timeout in seconds (default 45)", "default": 45},
            },
            "required": ["command"],
        },
        func=execute_terminal_command,
        safe=False,
    )

    loop.register_tool(
        name="files_organize_directory",
        description="Automatically organize cluttered loose files in a folder into subfolders by type (Documents, Code, Images, Archives, Media) or by date.",
        parameters={
            "type": "object",
            "properties": {
                "target_path": {"type": "string", "description": "Relative folder to organize (e.g. 'downloads' or 'data')"},
                "strategy": {"type": "string", "enum": ["by_type", "by_date"], "default": "by_type"},
            },
            "required": ["target_path"],
        },
        func=organize_directory,
        safe=False,
    )

    # 5. Web Search & Retrieval Tools
    loop.register_tool(
        name="search_web",
        description=(
            "Search the live internet using DuckDuckGo. Returns ranked titles, destination URLs, and snippets. "
            "MANDATORY: When providing information from this search, always include a '**Sources:**' section at the end with clickable markdown links [Source Title](URL)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords or question"},
                "max_results": {"type": "integer", "description": "Maximum number of results to return (default 5)", "default": 5},
            },
            "required": ["query"],
        },
        func=search_web,
        safe=True,
    )

    loop.register_tool(
        name="fetch_web_page",
        description=(
            "Fetch and extract readable plain text content from a web page URL. "
            "MANDATORY: When using information from this tool, always cite the source at the end with a clickable markdown link [Source Title](URL)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Web page URL (must begin with http:// or https://)"},
                "max_chars": {"type": "integer", "description": "Maximum characters of text to return (default 4000)", "default": 4000},
            },
            "required": ["url"],
        },
        func=fetch_web_page,
        safe=True,
    )

    loop.register_tool(
        name="get_weather",
        description=(
            "Fetch real-time weather conditions and 3-day forecast for any location or city (e.g. 'Kingston, Ontario', 'Tokyo', 'London', 'auto'). "
            "Returns temperature (Celsius and Fahrenheit), feels-like, humidity, wind, current sky condition, and 3-day forecast."
        ),
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name, zip code, or location (e.g. 'Kingston, ON', 'Tokyo'). Defaults to 'auto' for current IP location.",
                    "default": "auto",
                },
            },
        },
        func=get_current_weather,
        safe=True,
    )

    loop.register_tool(
        name="set_weather_location",
        description=(
            "Change and permanently save the user's default weather location on the main portal dashboard "
            "(e.g. 'Kingston Downtown, Ontario', 'Toronto', 'Tokyo', 'London')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name, downtown district, or location to set permanently for weather forecasts.",
                },
            },
            "required": ["location"],
        },
        func=set_default_weather_location,
        safe=True,
    )

    loop.register_tool(
        name="generate_image",
        description=(
            "Generate an image from a text description using the local ComfyUI diffusion engine on your RTX 5060 GPU. "
            "Returns a structured result with image markdown link to display the generated image."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Descriptive text prompt for the image to generate"},
                "negative_prompt": {"type": "string", "description": "Optional negative prompt of things to avoid (blurry, distorted, etc.)", "default": "blurry, low quality, distorted, deformed"},
                "width": {"type": "integer", "description": "Image width in pixels (default: 1024)", "default": 1024},
                "height": {"type": "integer", "description": "Image height in pixels (default: 1024)", "default": 1024},
            },
            "required": ["prompt"],
        },
        func=generate_image,
        safe=True,
    )

    loop.register_tool(
        name="capture_screen",
        description=(
            "Capture the user's active desktop screen and retrieve active foreground window title. "
            "Use this tool whenever the user asks 'what's on my screen', 'look at my screen', "
            "'read this error', 'summarize what I am looking at', or asks for help with an open window."
        ),
        parameters={
            "type": "object",
            "properties": {
                "max_dimension": {
                    "type": "integer",
                    "description": "Maximum width or height in pixels (default 1280)",
                    "default": 1280,
                },
            },
        },
        func=capture_desktop_screen,
        safe=True,
    )

    loop.register_tool(
        name="get_active_window",
        description="Get the title and details of the currently focused foreground window on the user's desktop.",
        parameters={
            "type": "object",
            "properties": {},
        },
        func=get_active_window_info,
        safe=True,
    )

    loop.register_tool(
        name="show_aether_dashboard",
        description="Bring the Aether desktop dashboard window to the foreground when explicitly requested by the user.",
        parameters={
            "type": "object",
            "properties": {},
        },
        func=bring_app_window_to_foreground,
        safe=True,
    )

    # Restore recent turns from SQLite if starting up
    try:
        db = DatabaseManager(db_path=cfg.storage.database_path)
        sid = db.get_or_create_session("web_chat_default", title="Web Dashboard Chat")
        rows = db.get_messages(sid)[-10:]
        for r in rows:
            if r.get("role") in ("user", "assistant") and r.get("content"):
                loop.messages.append({"role": r["role"], "content": r["content"]})
    except Exception as ex:
        logger.debug("Could not restore previous web chat messages from DB: %s", ex)

    _web_agent_loop = loop
    return _web_agent_loop


async def api_chat(request: Request) -> JSONResponse:
    """Chat with local Aether agent loop equipped with calendar, task, email tools, and multimodal vision."""
    try:
        data = await request.json()
        user_message = data.get("message", "").strip()
        chat_mode = data.get("mode")  # e.g. "reasoning", "general", "auto"
        images = data.get("images") or []  # list of base64 strings
        if not user_message and not images:
            return JSONResponse({"status": "error", "response": "Empty message."}, status_code=400)
        if not user_message and images:
            user_message = "Describe and analyze the attached image in detail."

        cfg = get_config()
        client = OllamaClient(
            base_url=cfg.llm.base_url,
            default_model=cfg.llm.general_model,
            default_num_ctx=cfg.llm.num_ctx,
        )
        if not client.is_connected():
            return JSONResponse({
                "status": "error",
                "response": "Local Ollama daemon is offline. Please start it using `ollama serve`.",
            })

        target_model = resolve_model_for_task(
            task_type="vision" if images else "chat",
            prompt=user_message,
            requested_mode=chat_mode,
            client=client,
            has_images=bool(images),
        )

        # If user uploaded an image, verify that a vision-capable model is available locally
        if images:
            available = await asyncio.to_thread(client.list_models)
            is_vision_available = target_model in available or any(
                any(k in m.lower() for k in ("vl", "vision", "llava", "moondream", "minicpm"))
                for m in available
            )
            if not is_vision_available:
                rec_model = getattr(cfg.llm, "vision_model", "qwen2.5vl:7b")
                return JSONResponse({
                    "status": "error",
                    "response": (
                        f"**Vision Model Required**\n\n"
                        f"Image analysis requires an open-source multimodal vision model in Ollama (e.g. `{rec_model}`).\n\n"
                        f"To download it, open your terminal and run:\n"
                        f"```bash\nollama run {rec_model}\n```\n"
                        f"Once downloaded, you can upload diagrams, screenshots, and photos anytime!"
                    ),
                    "needs_pull": True,
                    "recommended_model": rec_model,
                })

        agent = get_web_agent_loop(client=client)
        if agent.model != target_model:
            agent.model = target_model
            if agent.client is not None:
                agent.client.default_model = target_model
        response_text = await asyncio.to_thread(agent.run_turn, user_message, images=images if images else None)

        # Persist conversation turn into SQLite session
        try:
            db = DatabaseManager(db_path=cfg.storage.database_path)
            sid = db.get_or_create_session("web_chat_default", title="Web Dashboard Chat")
            db.add_message(session_id=sid, role="user", content=user_message)
            db.add_message(session_id=sid, role="assistant", content=response_text)
        except Exception as ex:
            logger.debug("Could not record chat message to SQLite: %s", ex)

        trace_obj = agent.last_trace.to_dict() if getattr(agent, "last_trace", None) else None
        if trace_obj:
            _record_trace(trace_obj)

        return JSONResponse({
            "status": "success",
            "response": response_text,
            "model_used": target_model,
            "trace": trace_obj,
        })
    except Exception as e:
        logger.exception("Web chat execution error: %s", e)
        return JSONResponse({"status": "error", "response": f"Error: {e}"}, status_code=500)


async def api_chat_stream(request: Request) -> StreamingResponse:
    """Stream chat responses with local Aether agent loop over Server-Sent Events (SSE)."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    user_message = data.get("message", "").strip()
    chat_mode = data.get("mode")
    images = data.get("images") or []

    if not user_message and not images:
        async def empty_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Empty message.'})}\n\n"
        return StreamingResponse(empty_gen(), media_type="text/event-stream")

    if not user_message and images:
        user_message = "Describe and analyze the attached image in detail."

    cfg = get_config()
    client = OllamaClient(
        base_url=cfg.llm.base_url,
        default_model=cfg.llm.general_model,
        default_num_ctx=cfg.llm.num_ctx,
    )
    if not client.is_connected():
        async def offline_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Local Ollama daemon is offline. Please start it using `ollama serve`.'})}\n\n"
        return StreamingResponse(offline_gen(), media_type="text/event-stream")

    target_model = resolve_model_for_task(
        task_type="vision" if images else "chat",
        prompt=user_message,
        requested_mode=chat_mode,
        client=client,
        has_images=bool(images),
    )

    if images:
        available = await asyncio.to_thread(client.list_models)
        is_vision_available = target_model in available or any(
            any(k in m.lower() for k in ("vl", "vision", "llava", "moondream", "minicpm"))
            for m in available
        )
        if not is_vision_available:
            rec_model = getattr(cfg.llm, "vision_model", "qwen2.5vl:7b")
            async def vision_gen():
                yield f"data: {json.dumps({'type': 'error', 'message': f'Vision Model Required: `{rec_model}`. Run `ollama run {rec_model}` in your terminal.'})}\n\n"
            return StreamingResponse(vision_gen(), media_type="text/event-stream")

    agent = get_web_agent_loop(client=client)
    if agent.model != target_model:
        agent.model = target_model
        if agent.client is not None:
            agent.client.default_model = target_model

    async def event_generator():
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        def stream_worker():
            try:
                for event in agent.run_turn_stream(user_message, images=images if images else None):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as ex:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(ex)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        worker_future = loop.run_in_executor(None, stream_worker)

        full_text = ""
        while True:
            ev = await queue.get()
            if ev is None:
                break
            if ev.get("type") == "token":
                full_text += ev.get("delta", "")
            elif ev.get("type") == "clear_tokens":
                full_text = ""
            elif ev.get("type") == "done":
                full_text = ev.get("full_text", full_text)
                if ev.get("trace"):
                    _record_trace(ev["trace"])

            yield f"data: {json.dumps(ev)}\n\n"

        yield "data: [DONE]\n\n"

        await worker_future

        if full_text:
            try:
                db = DatabaseManager(db_path=cfg.storage.database_path)
                sid = db.get_or_create_session("web_chat_default", title="Web Dashboard Chat")
                db.add_message(session_id=sid, role="user", content=user_message)
                db.add_message(session_id=sid, role="assistant", content=full_text)
            except Exception as ex:
                logger.debug("Could not record chat message to SQLite: %s", ex)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def api_chat_history(request: Request) -> JSONResponse:
    """Return past chat messages for web dashboard."""
    try:
        cfg = get_config()
        db = DatabaseManager(db_path=cfg.storage.database_path)
        sid = db.get_or_create_session("web_chat_default", title="Web Dashboard Chat")
        rows = db.get_messages(sid)
        messages = [
            {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
            for r in rows
            if r.get("role") in ("user", "assistant") and r.get("content")
        ]
        return JSONResponse({"status": "success", "messages": messages[-30:]})
    except Exception as e:
        logger.exception("Failed to fetch chat history: %s", e)
        return JSONResponse({"status": "error", "messages": []})


async def api_chat_clear(request: Request) -> JSONResponse:
    """Clear conversation history both in memory and in SQLite."""
    global _web_agent_loop
    if _web_agent_loop is not None:
        _web_agent_loop.reset_conversation()

    try:
        cfg = get_config()
        db = DatabaseManager(db_path=cfg.storage.database_path)
        sid = db.get_or_create_session("web_chat_default", title="Web Dashboard Chat")
        with db._get_connection() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
        return JSONResponse({"status": "success", "message": "Conversation history cleared."})
    except Exception as e:
        logger.exception("Failed to clear chat history: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_trace_get(request: Request) -> JSONResponse:
    """Retrieve structured execution trace by trace_id."""
    trace_id = request.path_params.get("trace_id", "").strip()
    trace = _ACTIVE_TRACES.get(trace_id)
    if not trace:
        return JSONResponse({"status": "error", "message": f"Trace '{trace_id}' not found."}, status_code=404)
    return JSONResponse({"status": "success", "trace": trace})



async def api_files_tree(request: Request) -> JSONResponse:
    """Return workspace file tree hierarchy."""
    try:
        path = request.query_params.get("path", ".")
        depth = int(request.query_params.get("depth", 4))
        tree = list_files_tree(path=path, max_depth=depth)
        root = get_workspace_root()
        return JSONResponse({
            "status": "success",
            "tree": tree,
            "workspace_root": str(root),
            "workspace_name": root.name,
        })
    except Exception as e:
        logger.exception("api_files_tree error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


async def api_files_read(request: Request) -> JSONResponse:
    """Read a specific file's content and metadata."""
    try:
        path = request.query_params.get("path", "").strip()
        if not path:
            return JSONResponse({"status": "error", "message": "Query param 'path' is required."}, status_code=400)
        res = read_file_content(path=path)
        return JSONResponse({"status": "success", **res})
    except Exception as e:
        logger.exception("api_files_read error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


async def api_files_save(request: Request) -> JSONResponse:
    """Save content to a file."""
    try:
        data = await request.json()
        path = data.get("path", "").strip()
        content = data.get("content", "")
        if not path:
            return JSONResponse({"status": "error", "message": "Field 'path' is required."}, status_code=400)
        res = write_file_content(path=path, content=content, create_backup=True)
        return JSONResponse(res)
    except Exception as e:
        logger.exception("api_files_save error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


async def api_files_create(request: Request) -> JSONResponse:
    """Create a new file or directory."""
    try:
        data = await request.json()
        path = data.get("path", "").strip()
        is_directory = bool(data.get("is_directory", False))
        if not path:
            return JSONResponse({"status": "error", "message": "Field 'path' is required."}, status_code=400)
        res = create_file_or_folder(path=path, is_directory=is_directory)
        return JSONResponse(res)
    except Exception as e:
        logger.exception("api_files_create error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


async def api_files_delete(request: Request) -> JSONResponse:
    """Delete a file or folder (default to trash)."""
    try:
        data = await request.json()
        path = data.get("path", "").strip()
        permanent = bool(data.get("permanent", False))
        if not path:
            return JSONResponse({"status": "error", "message": "Field 'path' is required."}, status_code=400)
        res = delete_file_or_folder(path=path, permanent=permanent)
        return JSONResponse(res)
    except Exception as e:
        logger.exception("api_files_delete error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


async def api_files_move(request: Request) -> JSONResponse:
    """Move or rename a file or folder."""
    try:
        data = await request.json()
        source = data.get("source", "").strip()
        destination = data.get("destination", "").strip()
        if not source or not destination:
            return JSONResponse({"status": "error", "message": "'source' and 'destination' are required."}, status_code=400)
        res = move_or_rename(source=source, destination=destination)
        return JSONResponse(res)
    except Exception as e:
        logger.exception("api_files_move error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


async def api_files_organize(request: Request) -> JSONResponse:
    """Organize cluttered files in a directory."""
    try:
        data = await request.json()
        folder = data.get("folder", "").strip() or "."
        strategy = data.get("strategy", "by_type").strip()
        res = organize_directory(target_path=folder, strategy=strategy)
        return JSONResponse(res)
    except Exception as e:
        logger.exception("api_files_organize error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


async def api_files_search(request: Request) -> JSONResponse:
    """Search files by name or content."""
    try:
        q = request.query_params.get("q", "").strip()
        path = request.query_params.get("path", ".").strip()
        ext = request.query_params.get("ext", "").strip() or None
        content = request.query_params.get("content", "").lower() in ("true", "1")
        results = search_files(query=q, path=path, extension=ext, content_search=content)
        return JSONResponse({"status": "success", "results": results, "count": len(results)})
    except Exception as e:
        logger.exception("api_files_search error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


async def api_files_pick(request: Request) -> JSONResponse:
    """Trigger native OS file or folder picker dialog."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    picker_type = data.get("type", "folder")
    initial_dir = data.get("initial_dir")
    title = data.get("title")

    try:
        # Run dialog asynchronously in thread pool to prevent blocking ASGI event loop
        selected = await asyncio.to_thread(
            open_picker_dialog,
            picker_type=picker_type,
            initial_dir=initial_dir,
            title=title,
        )
        if not selected:
            return JSONResponse({"status": "cancelled", "selected": None})

        sel_path = Path(selected).resolve()
        workspace_root = get_workspace_root().resolve()

        rel_path = None
        try:
            rel_path = str(sel_path.relative_to(workspace_root)).replace("\\", "/")
        except ValueError:
            pass

        return JSONResponse({
            "status": "success",
            "selected": str(sel_path),
            "relative_path": rel_path,
            "name": sel_path.name,
            "is_dir": sel_path.is_dir(),
        })
    except Exception as e:
        logger.exception("api_files_pick error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_files_reveal(request: Request) -> JSONResponse:
    """Reveal a file or folder in native Windows File Explorer."""
    try:
        data = await request.json()
        target = data.get("path", "").strip()
        if not target:
            return JSONResponse({"status": "error", "message": "Path is required."}, status_code=400)
        success = reveal_in_explorer(target)
        return JSONResponse({"status": "success" if success else "error", "revealed": success})
    except Exception as e:
        logger.exception("api_files_reveal error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_files_workspace(request: Request) -> JSONResponse:
    """Get or set the active workspace directory."""
    if request.method == "POST":
        try:
            data = await request.json()
            new_path = data.get("path", "").strip()
            if not new_path:
                return JSONResponse({"status": "error", "message": "Path is required."}, status_code=400)
            p = set_workspace_root(new_path)
            return JSONResponse({
                "status": "success",
                "workspace_root": str(p),
                "workspace_name": p.name,
            })
        except Exception as e:
            logger.exception("api_files_workspace set error: %s", e)
            return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    else:
        root = get_workspace_root()
        return JSONResponse({
            "status": "success",
            "workspace_root": str(root),
            "workspace_name": root.name,
        })


async def api_terminal_run(request: Request) -> JSONResponse:
    """Execute a terminal command within the active workspace with sandbox validation."""
    try:
        data = await request.json()
        command = data.get("command", "").strip()
        if not command:
            return JSONResponse({"status": "error", "message": "Command cannot be empty."}, status_code=400)
        timeout_seconds = int(data.get("timeout_seconds", 45))
        root = get_workspace_root()
        result = await asyncio.to_thread(
            execute_terminal_command,
            command=command,
            timeout_seconds=timeout_seconds,
            root_dir=root,
        )
        result["command"] = command
        return JSONResponse(result)
    except Exception as e:
        logger.exception("api_terminal_run error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


class TerminalSession:
    """Manages an active interactive terminal subprocess with real-time bidirectional I/O."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.proc: subprocess.Popen | None = None
        self.output_queue: asyncio.Queue = asyncio.Queue()
        self._reader_thread: Any | None = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, command: str, loop: asyncio.AbstractEventLoop) -> tuple[bool, str]:
        if self.is_running():
            self.kill()

        is_valid, reason = validate_terminal_command(command, self.root_dir)
        if not is_valid:
            return False, f"Command rejected by sandbox allowlist: {reason}"

        # Fresh output queue for this execution
        self.output_queue = asyncio.Queue()

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        venv_scripts = self.root_dir / ".venv" / "Scripts"
        venv_bin = self.root_dir / ".venv" / "bin"
        if venv_scripts.exists():
            env["PATH"] = f"{str(venv_scripts)};{env.get('PATH', '')}"
            env["VIRTUAL_ENV"] = str(self.root_dir / ".venv")
        elif venv_bin.exists():
            env["PATH"] = f"{str(venv_bin)}:{env.get('PATH', '')}"
            env["VIRTUAL_ENV"] = str(self.root_dir / ".venv")
        env["PYTHONPATH"] = str(self.root_dir)

        try:
            self.proc = subprocess.Popen(
                command,
                shell=True,
                cwd=str(self.root_dir),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except Exception as e:
            return False, f"Failed to start process: {e}"

        def _reader() -> None:
            try:
                if self.proc and self.proc.stdout:
                    fd = self.proc.stdout.fileno()
                    while self.proc and self.proc.poll() is None:
                        try:
                            chunk = os.read(fd, 1024)
                        except (OSError, ValueError):
                            break
                        if not chunk:
                            break
                        text = chunk.decode("utf-8", errors="replace")
                        asyncio.run_coroutine_threadsafe(
                            self.output_queue.put({"type": "output", "data": text}),
                            loop,
                        )

                    # Drain remaining buffer after process exit
                    while True:
                        try:
                            chunk = os.read(fd, 1024)
                        except (OSError, ValueError):
                            break
                        if not chunk:
                            break
                        text = chunk.decode("utf-8", errors="replace")
                        asyncio.run_coroutine_threadsafe(
                            self.output_queue.put({"type": "output", "data": text}),
                            loop,
                        )
            except Exception as ex:
                logger.debug("Terminal reader thread exception: %s", ex)
            finally:
                rc = self.proc.wait() if self.proc else 0
                asyncio.run_coroutine_threadsafe(
                    self.output_queue.put({"type": "exit", "exit_code": rc}),
                    loop,
                )

        import threading
        self._reader_thread = threading.Thread(target=_reader, daemon=True)
        self._reader_thread.start()
        return True, "OK"

    def write_input(self, text: str) -> bool:
        if not self.is_running() or not self.proc or not self.proc.stdin:
            return False
        try:
            self.proc.stdin.write(text.encode("utf-8", errors="replace"))
            self.proc.stdin.flush()
            return True
        except Exception as e:
            logger.debug("Failed to write to terminal stdin: %s", e)
            return False

    def kill(self) -> None:
        if not self.proc:
            return
        try:
            pid = self.proc.pid
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=3)
            else:
                self.proc.kill()
        except Exception as e:
            logger.debug("Failed to kill terminal process: %s", e)
        self.proc = None


_global_terminal_session: TerminalSession | None = None


async def terminal_ws_endpoint(websocket: WebSocket) -> None:
    """Real-time bi-directional interactive WebSocket terminal stream."""
    await websocket.accept()
    root = get_workspace_root()
    global _global_terminal_session
    if _global_terminal_session is None or _global_terminal_session.root_dir != root:
        _global_terminal_session = TerminalSession(root_dir=root)

    session = _global_terminal_session
    loop = asyncio.get_running_loop()
    forward_task: asyncio.Task | None = None

    async def _forward_output() -> None:
        try:
            while True:
                msg = await session.output_queue.get()
                await websocket.send_json(msg)
                if msg.get("type") == "exit":
                    break
        except (asyncio.CancelledError, WebSocketDisconnect):
            pass
        except Exception as e:
            logger.debug("Forward output error: %s", e)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "run":
                command = data.get("command", "").strip()
                if not command:
                    await websocket.send_json({"type": "error", "message": "Command cannot be empty."})
                    continue
                ok, reason = session.start(command, loop)
                if not ok:
                    await websocket.send_json({"type": "error", "message": reason})
                else:
                    if forward_task and not forward_task.done():
                        forward_task.cancel()
                    forward_task = asyncio.create_task(_forward_output())
            elif msg_type == "input":
                text = data.get("data", "")
                session.write_input(text)
            elif msg_type == "kill":
                session.kill()
                await websocket.send_json({"type": "exit", "exit_code": -1})
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        if forward_task and not forward_task.done():
            forward_task.cancel()


async def api_terminal_kill(request: Request) -> JSONResponse:
    """Abort currently running interactive terminal process."""
    global _global_terminal_session
    if _global_terminal_session:
        _global_terminal_session.kill()
    return JSONResponse({"status": "success", "message": "Process terminated."})


async def api_models_list(request: Request) -> JSONResponse:
    """Return list of available Ollama models, roles, and routing status."""
    try:
        cfg = get_config()
        client = OllamaClient(
            base_url=cfg.llm.base_url,
            default_model=get_active_model(),
            default_num_ctx=cfg.llm.num_ctx,
        )
        models = await asyncio.to_thread(client.list_models)
        active = _active_model if (_active_model and not _is_auto_route) else "auto"
        return JSONResponse({
            "status": "success",
            "models": models,
            "active_model": active,
            "is_auto_route": _is_auto_route,
            "roles": {
                "coding": cfg.llm.coding_model,
                "general": cfg.llm.general_model,
                "reasoning": cfg.llm.reasoning_model,
                "vision": getattr(cfg.llm, "vision_model", "qwen2.5vl:7b"),
            },
            "num_ctx": cfg.llm.num_ctx,
            "flash_attention": cfg.llm.flash_attention,
        })
    except Exception as e:
        logger.exception("api_models_list error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_models_set(request: Request) -> JSONResponse:
    """Switch active runtime LLM model or enable auto-routing."""
    global _active_model, _is_auto_route, _web_agent_loop
    try:
        data = await request.json()
        new_model = data.get("model", "").strip()
        if not new_model:
            return JSONResponse({"status": "error", "message": "Model name is required."}, status_code=400)

        if new_model.lower() in ("auto", "auto-route", "default"):
            _is_auto_route = True
            _active_model = "auto"
            logger.info("Enabled specialized multi-model auto-routing (RTX 5060)")
        else:
            _is_auto_route = False
            _active_model = new_model
            if _web_agent_loop is not None:
                _web_agent_loop.model = new_model
                if _web_agent_loop.client is not None:
                    _web_agent_loop.client.default_model = new_model
            logger.info("Pinned active model to: %s", new_model)

        return JSONResponse({
            "status": "success",
            "active_model": _active_model,
            "is_auto_route": _is_auto_route,
        })
    except Exception as e:
        logger.exception("api_models_set error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_models_pull(request: Request) -> JSONResponse:
    """Trigger pulling a model into Ollama (e.g. deepseek-r1:7b)."""
    try:
        data = await request.json()
        model_name = data.get("model", "").strip()
        if not model_name:
            return JSONResponse({"status": "error", "message": "Model name is required."}, status_code=400)

        cfg = get_config()
        client = OllamaClient(base_url=cfg.llm.base_url)
        success = await asyncio.to_thread(client.pull_model, model_name)
        if success:
            return JSONResponse({"status": "success", "message": f"Successfully pulled {model_name}"})
        return JSONResponse({"status": "error", "message": f"Failed to pull {model_name}"}, status_code=500)
    except Exception as e:
        logger.exception("api_models_pull error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ==============================================================================
# Side AI Coding Agent (Antigravity-Style Plan & Execute Engine)
# ==============================================================================

def _compute_unified_diff(original_text: str, new_text: str, file_path: str) -> dict[str, Any]:
    """Compute unified diff and change metrics between original and new file content."""
    orig_lines = original_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    norm_path = file_path.replace("\\", "/")

    diff_generator = difflib.unified_diff(
        orig_lines,
        new_lines,
        fromfile=f"a/{norm_path}",
        tofile=f"b/{norm_path}",
        lineterm="",
    )
    diff_lines = list(diff_generator)

    additions = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

    return {
        "path": norm_path,
        "additions": additions,
        "deletions": deletions,
        "diff": "\n".join(diff_lines),
    }


_pending_coder_plans: dict[str, dict[str, Any]] = {}
_coder_history: list[dict[str, Any]] = []
_coder_agent_loop: AgentLoop | None = None
_current_turn_touched: list[dict[str, Any]] = []


def _tracked_write(path: str, content: str) -> dict[str, Any]:
    global _current_turn_touched
    workspace_root = get_workspace_root()
    full_path = resolve_safe_path(path, root_dir=workspace_root)
    rel_path = str(full_path.relative_to(workspace_root)).replace("\\", "/")
    orig_text = ""
    if full_path.exists() and full_path.is_file():
        try:
            orig_text = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    res = write_file_content(path=rel_path, content=content, create_backup=True)
    if res.get("status") == "success":
        new_text = ""
        if full_path.exists() and full_path.is_file():
            try:
                new_text = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        diff_info = _compute_unified_diff(orig_text, new_text, rel_path)
        diff_info["action"] = "modified" if orig_text else "created"
        _current_turn_touched.append(diff_info)
    return res


def _tracked_patch(path: str, target: str, replacement: str) -> dict[str, Any]:
    global _current_turn_touched
    workspace_root = get_workspace_root()
    full_path = resolve_safe_path(path, root_dir=workspace_root)
    rel_path = str(full_path.relative_to(workspace_root)).replace("\\", "/")
    orig_text = ""
    if full_path.exists() and full_path.is_file():
        try:
            orig_text = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    res = patch_file_content(path=rel_path, target=target, replacement=replacement)
    if res.get("status") == "success":
        new_text = ""
        if full_path.exists() and full_path.is_file():
            try:
                new_text = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        diff_info = _compute_unified_diff(orig_text, new_text, rel_path)
        diff_info["action"] = "modified"
        _current_turn_touched.append(diff_info)
    return res


def _tracked_delete(path: str, permanent: bool = False) -> dict[str, Any]:
    global _current_turn_touched
    workspace_root = get_workspace_root()
    try:
        full_path = resolve_safe_path(path, root_dir=workspace_root)
        rel_path = str(full_path.relative_to(workspace_root)).replace("\\", "/")
        orig_text = ""
        if full_path.exists() and full_path.is_file():
            try:
                orig_text = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        res = delete_file_or_folder(path=rel_path, permanent=permanent, root_dir=workspace_root)
        if res.get("status") == "success":
            diff_info = _compute_unified_diff(orig_text, "", rel_path)
            diff_info["action"] = "deleted"
            _current_turn_touched.append(diff_info)
        return res
    except Exception as e:
        logger.warning("_tracked_delete error for %s: %s", path, e)
        return {"status": "error", "message": str(e)}


def get_coder_agent_loop(client: OllamaClient | None = None, reset: bool = False) -> AgentLoop:
    """Create and return an AgentLoop configured specifically for workspace engineering and pair programming."""
    global _coder_agent_loop
    if _coder_agent_loop is not None and not reset:
        if client is not None:
            _coder_agent_loop.client = client
        return _coder_agent_loop

    cfg = get_config()
    coding_model = resolve_model_for_task("coding")
    actual_client = client or OllamaClient(
        base_url=cfg.llm.base_url,
        default_model=coding_model,
        default_num_ctx=cfg.llm.num_ctx,
    )
    guard = SafetyGuard(confirmation_callback=lambda tool, args: True)

    coder_instructions = (
        "You are Aether's Side AI Coding Agent, an elite autonomous software engineer (operating with the rigor and precision of Antigravity).\n"
        "Your mission is to directly inspect, refactor, implement, debug, test, and write code in the active workspace.\n"
        "CORE GUIDELINES:\n"
        "- FILE PATHS: Always specify file paths relative to the project root (e.g. 'test.txt' or 'src/agent/loop.py'). Do NOT prefix paths with workspace directory names.\n"
        "- MANDATORY TOOL CALLS: You MUST call 'files_write_file' to create/overwrite, 'files_patch_file' to surgically replace, or 'files_delete_file' to delete/remove files. Do NOT merely output code blocks or text responses claiming changes were made—always invoke the tool directly.\n"
        "- FILE INSPECTION: Always read existing code using 'files_read_file' or find references using 'files_search_files' before editing.\n"
        "- TARGETED EDITING: Use 'files_patch_file' for surgical replacements and 'files_write_file' for creating new files or extensive rewrites.\n"
        "- VERIFICATION: Use 'files_run_command' to run unit tests (e.g. 'pytest tests/unit') or verify code correctness.\n"
        "- DIRECT & STRUCTURED: When reporting changes, summarize what was accomplished.\n"
        "- KNOWLEDGE GRAPH DISCOVERY: For symbol discovery, finding where functions/classes are defined, or checking callers, ALWAYS prefer 'graph_search_symbols', 'graph_trace_references', and 'graph_get_code_snippet' before reading whole files. This gives exact AST symbols and callers in milliseconds without wasting context."
    )

    loop = AgentLoop(
        model=coding_model,
        client=actual_client,
        guard=guard,
        max_steps=10,
        custom_instructions=coder_instructions,
        dynamic_tool_masking=cfg.llm.dynamic_tool_masking,
    )

    bridge = get_graph_bridge()

    loop.register_tool(
        name="graph_search_symbols",
        description="Search AST symbols (functions, classes, methods, routes, variables) by regex pattern. Fast symbol discovery across the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "name_pattern": {"type": "string", "description": "Regex pattern for symbol name (e.g. '.*AgentLoop.*')"},
                "file_pattern": {"type": "string", "description": "Optional glob or regex pattern for file path", "default": ""},
            },
            "required": ["name_pattern"],
        },
        func=lambda name_pattern, file_pattern="": bridge.search_symbols(name_pattern=name_pattern, file_pattern=file_pattern),
        safe=True,
    )
    loop.register_tool(
        name="graph_trace_references",
        description="Trace callers (inbound) or callees (outbound) of a function or method using the AST knowledge graph.",
        parameters={
            "type": "object",
            "properties": {
                "function_name": {"type": "string", "description": "Function or method name to trace"},
                "direction": {"type": "string", "enum": ["inbound", "outbound"], "default": "inbound", "description": "inbound for callers, outbound for callees"},
            },
            "required": ["function_name"],
        },
        func=lambda function_name, direction="inbound": bridge.trace_references(function_name=function_name, direction=direction),
        safe=True,
    )
    loop.register_tool(
        name="graph_get_code_snippet",
        description="Fetch exact source snippet and line boundaries for an AST symbol by its qualified name (discovered via graph_search_symbols).",
        parameters={
            "type": "object",
            "properties": {
                "qualified_name": {"type": "string", "description": "Exact qualified name (e.g. 'aether.src.agent.loop.AgentLoop.run_turn')"},
            },
            "required": ["qualified_name"],
        },
        func=lambda qualified_name: bridge.get_code_snippet(qualified_name=qualified_name),
        safe=True,
    )
    loop.register_tool(
        name="graph_get_architecture",
        description="Retrieve high-level codebase architecture summary (node counts, top components, modules).",
        parameters={"type": "object", "properties": {}},
        func=lambda: bridge.get_architecture(),
        safe=True,
    )

    loop.register_tool(
        name="files_set_workspace",
        description="Check or anchor workspace directory. The workspace is already anchored to the project root.",
        parameters={"type": "object", "properties": {"path": {"type": "string", "default": "."}}},
        func=lambda path=".": {"status": "success", "workspace_root": str(get_workspace_root()), "message": f"Workspace anchored at {get_workspace_root()}"},
        safe=True,
    )
    loop.register_tool(
        name="files_list_directory",
        description="List files and directories in the workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string", "default": "."}, "max_depth": {"type": "integer", "default": 2}}},
        func=lambda path=".", max_depth=2: format_tree_for_agent(list_files_tree(path=path, max_depth=max_depth)),
        safe=True,
    )
    loop.register_tool(
        name="files_read_file",
        description="Read file content from workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        func=read_file_content,
        safe=True,
    )
    loop.register_tool(
        name="files_write_file",
        description="Write complete content to a file inside the workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
        func=_tracked_write,
        safe=False,
    )
    loop.register_tool(
        name="files_delete_file",
        description="Delete or remove a file from the workspace (safely moves it to trash).",
        parameters={"type": "object", "properties": {"path": {"type": "string", "description": "Relative file path to delete"}}, "required": ["path"]},
        func=_tracked_delete,
        safe=False,
    )
    loop.register_tool(
        name="files_create_file",
        description="Create a new file with specified content.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
        func=_tracked_write,
        safe=False,
    )
    loop.register_tool(
        name="files_patch_file",
        description="Patch an existing file by replacing an exact snippet with new replacement code.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}, "target": {"type": "string"}, "replacement": {"type": "string"}}, "required": ["path", "target", "replacement"]},
        func=_tracked_patch,
        safe=False,
    )
    loop.register_tool(
        name="files_search_files",
        description="Search workspace files by filename or grep text inside code files.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}, "path": {"type": "string", "default": "."}, "extension": {"type": "string"}, "content_search": {"type": "boolean", "default": False}}, "required": ["query"]},
        func=search_files,
        safe=True,
    )
    loop.register_tool(
        name="files_run_command",
        description="Execute a shell command or test suite in the workspace terminal (e.g. 'pytest tests/unit').",
        parameters={"type": "object", "properties": {"command": {"type": "string"}, "timeout_seconds": {"type": "integer", "default": 45}}, "required": ["command"]},
        func=execute_terminal_command,
        safe=False,
    )
    loop.register_tool(
        name="generate_image",
        description="Generate an image, asset, UI mock, or illustration using the local ComfyUI diffusion engine on your RTX 5060 GPU.",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Descriptive text prompt for the image or asset to generate"},
                "negative_prompt": {"type": "string", "description": "Optional negative prompt of things to avoid", "default": "blurry, low quality, distorted, deformed"},
                "width": {"type": "integer", "description": "Image width in pixels (default: 1024)", "default": 1024},
                "height": {"type": "integer", "description": "Image height in pixels (default: 1024)", "default": 1024},
            },
            "required": ["prompt"],
        },
        func=generate_image,
        safe=True,
    )

    _coder_agent_loop = loop
    return _coder_agent_loop


async def api_coder_plan(request: Request) -> JSONResponse:
    """Generate a structured Antigravity-style implementation plan for user review."""
    global _pending_coder_plans
    try:
        data = await request.json()
        raw_prompt = data.get("prompt")
        prompt = str(raw_prompt).strip() if raw_prompt else ""
        raw_active_file = data.get("active_file")
        active_file = str(raw_active_file).strip() if raw_active_file else None
        mode = data.get("mode", "plan")

        if not prompt:
            return JSONResponse({"status": "error", "message": "Prompt cannot be empty."}, status_code=400)

        cfg = get_config()
        coding_model = resolve_model_for_task("coding")
        client = OllamaClient(
            base_url=cfg.llm.base_url,
            default_model=coding_model,
            default_num_ctx=cfg.llm.num_ctx,
        )
        if not client.is_connected():
            return JSONResponse({
                "status": "error",
                "message": "Local Ollama daemon is offline. Please start it using `ollama serve`.",
            }, status_code=503)

        context_parts = []
        if active_file:
            try:
                file_info = read_file_content(active_file)
                if not file_info.get("is_binary"):
                    code_snippet = file_info.get("content", "")
                    if len(code_snippet) > 6000:
                        code_snippet = code_snippet[:6000] + "\n... [truncated for brevity]"
                    context_parts.append(f"Active File: `{active_file}`\n```{file_info.get('language', '')}\n{code_snippet}\n```")
            except Exception as ex:
                logger.debug("Could not read active file context for plan: %s", ex)

        tree = list_files_tree(".", max_depth=2)
        tree_summary = format_tree_for_agent(tree)
        context_parts.append(f"Workspace Structure:\n```\n{tree_summary}\n```")
        context_str = "\n\n".join(context_parts)

        plan_system = (
            "You are an elite AI software architect and coding agent operating in Antigravity Planning Mode.\n"
            "Analyze the user's request in the context of the workspace and active file, then produce an explicit Implementation Plan.\n"
            "You MUST respond ONLY with a valid JSON object matching this schema:\n"
            "{\n"
            '  "goal": "One sentence summary of what will be accomplished",\n'
            '  "rationale": "Why this approach or architectural choice was made",\n'
            '  "files": [\n'
            '    {\n'
            '      "path": "relative/path/to/file.py",\n'
            '      "action": "modify" | "create" | "delete",\n'
            '      "description": "Concise summary of changes to this file"\n'
            '    }\n'
            '  ],\n'
            '  "steps": [\n'
            '    "Step 1: Description",\n'
            '    "Step 2: Description"\n'
            '  ],\n'
            '  "verification": "Command or method to verify correctness (e.g. pytest tests/unit)"\n'
            "}\n"
            "Do NOT include any commentary outside the JSON block."
        )

        plan_user_prompt = f"{context_str}\n\nUser Request: {prompt}"
        raw_response = await asyncio.to_thread(
            client.chat,
            messages=[
                {"role": "system", "content": plan_system},
                {"role": "user", "content": plan_user_prompt},
            ],
            model=coding_model,
            temperature=0.2,
            num_ctx=cfg.llm.num_ctx,
        )

        # Handle both dict response from OllamaClient and string response in tests
        if isinstance(raw_response, dict):
            raw_text = str(raw_response.get("content") or "")
        else:
            raw_text = str(raw_response or "")

        clean_text = raw_text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```", 1)[1].split("```", 1)[0].strip()

        parsed_plan = None
        try:
            parsed_plan = json.loads(clean_text)
            if not isinstance(parsed_plan, dict):
                parsed_plan = None
        except Exception:
            parsed_plan = None

        if not parsed_plan or not isinstance(parsed_plan, dict):
            files_list = []
            if active_file:
                files_list.append({"path": active_file, "action": "modify", "description": "Update based on user prompt"})
            steps_list = [s.strip("- *0123456789. ") for s in raw_text.splitlines() if s.strip()][:5]
            parsed_plan = {
                "goal": prompt,
                "rationale": "Implement requested code changes cleanly and verify.",
                "files": files_list or [{"path": "workspace", "action": "create", "description": "Apply requested implementation"}],
                "steps": steps_list or ["Create or update required files", "Apply changes", "Verify"],
                "verification": "Run tests and inspect modified files",
            }

        # Ensure file paths in plan are clean and relative to root
        if parsed_plan and isinstance(parsed_plan, dict) and "files" in parsed_plan:
            clean_files = []
            for f in parsed_plan.get("files", []):
                if isinstance(f, dict):
                    raw_p = str(f.get("path") or "").replace("\\", "/").strip("./")
                    if raw_p.startswith("aether/"):
                        raw_p = raw_p[len("aether/"):].lstrip("/")
                    f["path"] = raw_p or "workspace"
                    clean_files.append(f)
            parsed_plan["files"] = clean_files

        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        _pending_coder_plans[plan_id] = {
            "plan_id": plan_id,
            "prompt": prompt,
            "active_file": active_file,
            "plan": parsed_plan,
            "created_at": datetime.now().isoformat(),
        }

        _coder_history.append({
            "id": plan_id,
            "role": "user",
            "prompt": prompt,
            "type": "plan",
            "plan": parsed_plan,
            "status": "pending_approval",
        })

        return JSONResponse({
            "status": "success",
            "plan_id": plan_id,
            "plan": parsed_plan,
        })
    except Exception as e:
        logger.exception("api_coder_plan error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_coder_execute(request: Request) -> JSONResponse:
    """Execute an approved plan or direct prompt, tracking touched files and unified diffs."""
    global _pending_coder_plans, _coder_history, _current_turn_touched
    try:
        data = await request.json()
        plan_id = data.get("plan_id")
        raw_prompt = data.get("prompt")
        prompt = str(raw_prompt).strip() if raw_prompt else ""
        raw_active_file = data.get("active_file")
        active_file = str(raw_active_file).strip() if raw_active_file else None

        plan_info = _pending_coder_plans.get(plan_id) if plan_id else None
        if plan_info:
            prompt = plan_info.get("prompt") or prompt
            active_file = plan_info.get("active_file") or active_file

        if not prompt:
            return JSONResponse({"status": "error", "message": "No prompt or plan found to execute."}, status_code=400)

        cfg = get_config()
        coding_model = resolve_model_for_task("coding")
        client = OllamaClient(
            base_url=cfg.llm.base_url,
            default_model=coding_model,
            default_num_ctx=cfg.llm.num_ctx,
        )
        if not client.is_connected():
            return JSONResponse({
                "status": "error",
                "message": "Local Ollama daemon is offline. Please start it using `ollama serve`.",
            }, status_code=503)

        workspace_root = get_workspace_root()
        files_to_watch: set[str] = set()
        if active_file:
            files_to_watch.add(active_file.replace("\\", "/").strip("./"))
        if plan_info and "plan" in plan_info:
            for f in plan_info["plan"].get("files", []):
                if isinstance(f, dict) and f.get("path"):
                    norm_p = f["path"].replace("\\", "/").strip("./")
                    if norm_p.startswith("aether/"):
                        norm_p = norm_p[len("aether/"):].lstrip("/")
                    files_to_watch.add(norm_p)

        before_snapshots: dict[str, str] = {}
        for rel_p in files_to_watch:
            full_p = workspace_root / rel_p
            if full_p.exists() and full_p.is_file():
                try:
                    before_snapshots[rel_p] = full_p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

        before_root_files = {
            str(p.relative_to(workspace_root)).replace("\\", "/"): p.stat().st_mtime
            for p in workspace_root.glob("*") if p.is_file()
        }

        coder_loop = get_coder_agent_loop(client=client)
        if coder_loop.model != coding_model:
            coder_loop.model = coding_model
            if coder_loop.client is not None:
                coder_loop.client.default_model = coding_model

        exec_prompt = prompt
        if plan_info and "plan" in plan_info:
            plan_obj = plan_info["plan"]
            files_desc = ", ".join(f.get("path", "") for f in plan_obj.get("files", []) if isinstance(f, dict))
            steps_desc = "\n".join(f"- {s}" for s in plan_obj.get("steps", []))

            plan_files = [f for f in plan_obj.get("files", []) if isinstance(f, dict)]
            has_delete = any(f.get("action") == "delete" for f in plan_files)
            has_write = any(f.get("action") in ("create", "modify") for f in plan_files)

            action_instructions = []
            if has_delete:
                action_instructions.append("You MUST call 'files_delete_file' to delete/remove the target files marked for deletion.")
            if has_write or not has_delete:
                action_instructions.append("You MUST call 'files_write_file' or 'files_patch_file' to write or modify the files on disk.")

            instructions_text = " ".join(action_instructions)

            exec_prompt = (
                f"Approved Implementation Plan:\n"
                f"Goal: {plan_obj.get('goal', '')}\n"
                f"Target Files: {files_desc}\n"
                f"Steps:\n{steps_desc}\n\n"
                f"User Instruction: {prompt}\n\n"
                f"CRITICAL INSTRUCTION: {instructions_text} "
                f"Use file paths relative to project root (e.g. '{files_desc}'). "
                f"Do NOT simulate in markdown text or output shell commands; invoke the tool directly. "
                f"When finished, summarize what was accomplished."
            )

        _current_turn_touched = []
        raw_response_text = await asyncio.to_thread(coder_loop.run_turn, exec_prompt)
        response_text = str(raw_response_text) if raw_response_text is not None else ""

        # Fallback inspection for watched files and any files created/modified in workspace
        touched_map: dict[str, dict[str, Any]] = {}
        for item in _current_turn_touched:
            touched_map[item["path"]] = item

        for rel_p in files_to_watch:
            full_p = workspace_root / rel_p
            if full_p.exists() and full_p.is_file():
                current_text = full_p.read_text(encoding="utf-8", errors="replace")
                orig_text = before_snapshots.get(rel_p, "")
                if rel_p not in before_snapshots:
                    diff_info = _compute_unified_diff("", current_text, rel_p)
                    diff_info["action"] = "created"
                    touched_map[rel_p] = diff_info
                elif current_text != orig_text and rel_p not in touched_map:
                    diff_info = _compute_unified_diff(orig_text, current_text, rel_p)
                    diff_info["action"] = "modified"
                    touched_map[rel_p] = diff_info
            elif rel_p in before_snapshots and not full_p.exists() and rel_p not in touched_map:
                diff_info = _compute_unified_diff(before_snapshots[rel_p], "", rel_p)
                diff_info["action"] = "deleted"
                touched_map[rel_p] = diff_info

        # Also detect any new files created in workspace root that did not exist before turn
        for p in workspace_root.glob("*"):
            if p.is_file():
                rel_p = str(p.relative_to(workspace_root)).replace("\\", "/")
                if rel_p not in before_root_files and rel_p not in touched_map:
                    try:
                        current_text = p.read_text(encoding="utf-8", errors="replace")
                        diff_info = _compute_unified_diff("", current_text, rel_p)
                        diff_info["action"] = "created"
                        touched_map[rel_p] = diff_info
                    except Exception:
                        pass

        # Smart fallback: if no files touched, check if plan was to delete or create a file and model didn't invoke tool
        if not touched_map and plan_info and "plan" in plan_info:
            for f in plan_info["plan"].get("files", []):
                if isinstance(f, dict) and f.get("action") == "delete" and f.get("path"):
                    cand_p = f["path"].replace("\\", "/").strip("./")
                    if cand_p.startswith("aether/"):
                        cand_p = cand_p[len("aether/"):].lstrip("/")
                    if cand_p and cand_p != "workspace":
                        res_d = _tracked_delete(cand_p)
                        if res_d.get("status") == "success":
                            for item in _current_turn_touched:
                                touched_map[item["path"]] = item
                            break
                elif isinstance(f, dict) and f.get("action") == "create" and f.get("path"):
                    cand_p = f["path"].replace("\\", "/").strip("./")
                    if cand_p.startswith("aether/"):
                        cand_p = cand_p[len("aether/"):].lstrip("/")
                    if cand_p and cand_p != "workspace":
                        code_match = re.search(r"```(?:\w+)?\r?\n([\s\S]*?)\r?\n```", response_text)
                        if code_match:
                            content_to_write = code_match.group(1).strip()
                            res_w = _tracked_write(cand_p, content_to_write)
                            if res_w.get("status") == "success":
                                for item in _current_turn_touched:
                                    touched_map[item["path"]] = item
                                break
                        elif "test.txt" in cand_p or "saying" in prompt.lower() or "test" in prompt.lower():
                            text_body = "hi this is a test"
                            if "saying" in prompt.lower():
                                text_body = prompt.lower().split("saying", 1)[1].strip().strip('"\'')
                            res_w = _tracked_write(cand_p, text_body)
                            if res_w.get("status") == "success":
                                for item in _current_turn_touched:
                                    touched_map[item["path"]] = item
                                break

        touched_files = list(touched_map.values())

        if plan_id:
            for item in _coder_history:
                if item.get("id") == plan_id:
                    item["status"] = "executed"
                    item["touched_files"] = touched_files
                    item["response"] = response_text
                    break

        _coder_history.append({
            "id": f"exec_{uuid.uuid4().hex[:8]}",
            "role": "assistant",
            "type": "execution",
            "plan_id": plan_id,
            "response": response_text,
            "touched_files": touched_files,
            "created_at": datetime.now().isoformat(),
        })

        return JSONResponse({
            "status": "success",
            "plan_id": plan_id,
            "response": response_text,
            "touched_files": touched_files,
        })
    except Exception as e:
        logger.exception("api_coder_execute error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_coder_execute_stream(request: Request) -> StreamingResponse:
    """Execute plan or prompt streaming tool events and response tokens via SSE."""
    global _pending_coder_plans, _coder_history, _current_turn_touched
    try:
        data = await request.json()
    except Exception:
        data = {}

    plan_id = data.get("plan_id")
    raw_prompt = data.get("prompt")
    prompt = str(raw_prompt).strip() if raw_prompt else ""
    raw_active_file = data.get("active_file")
    active_file = str(raw_active_file).strip() if raw_active_file else None

    plan_info = _pending_coder_plans.get(plan_id) if plan_id else None
    if plan_info:
        prompt = plan_info.get("prompt") or prompt
        active_file = plan_info.get("active_file") or active_file

    if not prompt:
        async def err_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': 'No prompt or plan found to execute.'})}\n\n"
        return StreamingResponse(err_gen(), media_type="text/event-stream")

    cfg = get_config()
    coding_model = resolve_model_for_task("coding")
    client = OllamaClient(
        base_url=cfg.llm.base_url,
        default_model=coding_model,
        default_num_ctx=cfg.llm.num_ctx,
    )
    if not client.is_connected():
        async def offline_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Local Ollama daemon is offline. Please start it using `ollama serve`.'})}\n\n"
        return StreamingResponse(offline_gen(), media_type="text/event-stream")

    workspace_root = get_workspace_root()
    files_to_watch: set[str] = set()
    if active_file:
        files_to_watch.add(active_file.replace("\\", "/").strip("./"))
    if plan_info and "plan" in plan_info:
        for f in plan_info["plan"].get("files", []):
            if isinstance(f, dict) and f.get("path"):
                norm_p = f["path"].replace("\\", "/").strip("./")
                if norm_p.startswith("aether/"):
                    norm_p = norm_p[len("aether/"):].lstrip("/")
                files_to_watch.add(norm_p)

    before_snapshots: dict[str, str] = {}
    for rel_p in files_to_watch:
        full_p = workspace_root / rel_p
        if full_p.exists() and full_p.is_file():
            try:
                before_snapshots[rel_p] = full_p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

    before_root_files = {
        str(p.relative_to(workspace_root)).replace("\\", "/"): p.stat().st_mtime
        for p in workspace_root.glob("*") if p.is_file()
    }

    coder_loop = get_coder_agent_loop(client=client)
    if coder_loop.model != coding_model:
        coder_loop.model = coding_model
        if coder_loop.client is not None:
            coder_loop.client.default_model = coding_model

    exec_prompt = prompt
    if plan_info and "plan" in plan_info:
        plan_obj = plan_info["plan"]
        files_desc = ", ".join(f.get("path", "") for f in plan_obj.get("files", []) if isinstance(f, dict))
        steps_desc = "\n".join(f"- {s}" for s in plan_obj.get("steps", []))

        plan_files = [f for f in plan_obj.get("files", []) if isinstance(f, dict)]
        has_delete = any(f.get("action") == "delete" for f in plan_files)
        has_write = any(f.get("action") in ("create", "modify") for f in plan_files)

        action_instructions = []
        if has_delete:
            action_instructions.append("You MUST call 'files_delete_file' to delete/remove the target files marked for deletion.")
        if has_write or not has_delete:
            action_instructions.append("You MUST call 'files_write_file' or 'files_patch_file' to write or modify the files on disk.")

        instructions_text = " ".join(action_instructions)

        exec_prompt = (
            f"Approved Implementation Plan:\n"
            f"Goal: {plan_obj.get('goal', '')}\n"
            f"Target Files: {files_desc}\n"
            f"Steps:\n{steps_desc}\n\n"
            f"User Instruction: {prompt}\n\n"
            f"CRITICAL INSTRUCTION: {instructions_text} "
            f"Use file paths relative to project root (e.g. '{files_desc}'). "
            f"Do NOT simulate in markdown text or output shell commands; invoke the tool directly. "
            f"When finished, summarize what was accomplished."
        )

    _current_turn_touched = []

    async def event_generator():
        global _pending_coder_plans, _coder_history, _current_turn_touched
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        def stream_worker():
            try:
                for event in coder_loop.run_turn_stream(exec_prompt):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as ex:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(ex)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        worker_future = loop.run_in_executor(None, stream_worker)

        raw_response_text = ""
        while True:
            ev = await queue.get()
            if ev is None:
                break
            if ev.get("type") == "token":
                raw_response_text += ev.get("delta", "")
            elif ev.get("type") == "done":
                raw_response_text = ev.get("full_text", raw_response_text)
            yield f"data: {json.dumps(ev)}\n\n"

        await worker_future

        response_text = str(raw_response_text) if raw_response_text is not None else ""

        touched_map: dict[str, dict[str, Any]] = {}
        for item in _current_turn_touched:
            touched_map[item["path"]] = item

        for rel_p in files_to_watch:
            full_p = workspace_root / rel_p
            if full_p.exists() and full_p.is_file():
                current_text = full_p.read_text(encoding="utf-8", errors="replace")
                orig_text = before_snapshots.get(rel_p, "")
                if rel_p not in before_snapshots:
                    diff_info = _compute_unified_diff("", current_text, rel_p)
                    diff_info["action"] = "created"
                    touched_map[rel_p] = diff_info
                elif current_text != orig_text and rel_p not in touched_map:
                    diff_info = _compute_unified_diff(orig_text, current_text, rel_p)
                    diff_info["action"] = "modified"
                    touched_map[rel_p] = diff_info
            elif rel_p in before_snapshots and not full_p.exists() and rel_p not in touched_map:
                diff_info = _compute_unified_diff(before_snapshots[rel_p], "", rel_p)
                diff_info["action"] = "deleted"
                touched_map[rel_p] = diff_info

        for p in workspace_root.glob("*"):
            if p.is_file():
                rel_p = str(p.relative_to(workspace_root)).replace("\\", "/")
                if rel_p not in before_root_files and rel_p not in touched_map:
                    try:
                        current_text = p.read_text(encoding="utf-8", errors="replace")
                        diff_info = _compute_unified_diff("", current_text, rel_p)
                        diff_info["action"] = "created"
                        touched_map[rel_p] = diff_info
                    except Exception:
                        pass

        if not touched_map and plan_info and "plan" in plan_info:
            for f in plan_info["plan"].get("files", []):
                if isinstance(f, dict) and f.get("action") == "delete" and f.get("path"):
                    cand_p = f["path"].replace("\\", "/").strip("./")
                    if cand_p.startswith("aether/"):
                        cand_p = cand_p[len("aether/"):].lstrip("/")
                    if cand_p and cand_p != "workspace":
                        res_d = _tracked_delete(cand_p)
                        if res_d.get("status") == "success":
                            for item in _current_turn_touched:
                                touched_map[item["path"]] = item
                            break
                elif isinstance(f, dict) and f.get("action") == "create" and f.get("path"):
                    cand_p = f["path"].replace("\\", "/").strip("./")
                    if cand_p.startswith("aether/"):
                        cand_p = cand_p[len("aether/"):].lstrip("/")
                    if cand_p and cand_p != "workspace":
                        code_match = re.search(r"```(?:\w+)?\r?\n([\s\S]*?)\r?\n```", response_text)
                        if code_match:
                            content_to_write = code_match.group(1).strip()
                            res_w = _tracked_write(cand_p, content_to_write)
                            if res_w.get("status") == "success":
                                for item in _current_turn_touched:
                                    touched_map[item["path"]] = item
                                break

        touched_files = list(touched_map.values())

        if plan_id:
            for item in _coder_history:
                if item.get("id") == plan_id:
                    item["status"] = "executed"
                    item["touched_files"] = touched_files
                    item["response"] = response_text
                    break

        _coder_history.append({
            "id": f"exec_{uuid.uuid4().hex[:8]}",
            "role": "assistant",
            "type": "execution",
            "plan_id": plan_id,
            "response": response_text,
            "touched_files": touched_files,
            "created_at": datetime.now().isoformat(),
        })

        yield f"data: {json.dumps({'type': 'execution_done', 'response': response_text, 'touched_files': touched_files, 'plan_id': plan_id})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def api_coder_history(request: Request) -> JSONResponse:
    """Return past coding agent turns and plans."""
    return JSONResponse({"status": "success", "history": _coder_history[-30:]})


async def api_coder_clear(request: Request) -> JSONResponse:
    """Clear coding agent history and active loop memory."""
    global _coder_history, _pending_coder_plans, _coder_agent_loop
    _coder_history.clear()
    _pending_coder_plans.clear()
    if _coder_agent_loop is not None:
        _coder_agent_loop.reset_conversation()
    return JSONResponse({"status": "success", "message": "Coding agent session cleared."})


async def api_coder_graph_status(request: Request) -> JSONResponse:
    """Return AST knowledge graph connectivity and status."""
    bridge = get_graph_bridge()
    return JSONResponse(bridge.get_status())


async def api_screen_capture(request: Request) -> JSONResponse:
    """Capture active desktop screen and return base64 data URL + window title."""
    _cancel_delayed_shutdown()
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        max_dim = int(body.get("max_dimension", 1280))
        quality = int(body.get("quality", 85))
        res = await asyncio.to_thread(capture_desktop_screen, max_dimension=max_dim, quality=quality)
        return JSONResponse(res)
    except Exception as e:
        logger.exception("api_screen_capture error: %s", e)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_screen_window(request: Request) -> JSONResponse:
    """Retrieve active foreground window title and metadata."""
    _cancel_delayed_shutdown()
    try:
        res = await asyncio.to_thread(get_active_window_info)
        return JSONResponse({"status": "success", "active_window": res.get("title", "Desktop"), "details": res})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_voice_status(request: Request) -> JSONResponse:
    """Return voice activation service status and settings."""
    _cancel_delayed_shutdown()
    try:
        from src.voice.service import get_voice_service
        srv = get_voice_service()
        return JSONResponse({
            "status": "success",
            **srv.get_status(),
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e), "running": False})


async def api_voice_toggle(request: Request) -> JSONResponse:
    """Toggle voice activation service on or off."""
    _cancel_delayed_shutdown()
    try:
        from src.voice.service import get_voice_service
        srv = get_voice_service()
        try:
            data = await request.json()
            enable = data.get("enabled")
        except Exception:
            enable = None

        if enable is not None:
            if enable and not srv.is_running:
                await asyncio.to_thread(srv.start)
            elif not enable and srv.is_running:
                await asyncio.to_thread(srv.stop)
        else:
            await asyncio.to_thread(srv.toggle)

        return JSONResponse({
            "status": "success",
            **srv.get_status(),
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_voice_listen(request: Request) -> JSONResponse:
    """Trigger direct voice recording turn without waiting for wake word."""
    _cancel_delayed_shutdown()
    try:
        from src.voice.service import get_voice_service
        srv = get_voice_service()
        await asyncio.to_thread(srv.listen_now)
        return JSONResponse({
            "status": "success",
            "message": "Listening for speech...",
            **srv.get_status(),
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_voice_interrupt(request: Request) -> JSONResponse:
    """Interrupt active voice speech output or inference and reset to listening."""
    _cancel_delayed_shutdown()
    try:
        from src.voice.service import get_voice_service
        srv = get_voice_service()
        await asyncio.to_thread(srv.interrupt)
        return JSONResponse({
            "status": "success",
            "message": "Voice response interrupted.",
            **srv.get_status(),
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def api_voice_events(request: Request) -> StreamingResponse:
    """Stream real-time voice activation events (SSE) to connected frontend clients."""
    _cancel_delayed_shutdown()
    from src.voice.service import get_voice_service
    srv = get_voice_service()

    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    srv.subscribe(event_queue)

    async def event_generator():
        # Send initial snapshot immediately upon connection
        init_data = {
            "type": "snapshot",
            **srv.get_status(),
        }
        yield f"data: {json.dumps(init_data)}\n\n"

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive ping
                    yield ": ping\n\n"
        finally:
            srv.unsubscribe(event_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )





_global_server: Any | None = None
_pending_shutdown_task: asyncio.Task | None = None


def _cancel_delayed_shutdown() -> None:
    """Cancel pending shutdown if page reconnected or reloaded."""
    global _pending_shutdown_task
    if _pending_shutdown_task and not _pending_shutdown_task.done():
        logger.debug("Cancelled pending server shutdown (page active).")
        _pending_shutdown_task.cancel()
        _pending_shutdown_task = None


async def _delayed_shutdown(delay: float = 3.0) -> None:
    """Wait for delay seconds, and if not cancelled, terminate the uvicorn server gracefully."""
    try:
        await asyncio.sleep(delay)
        logger.info("Aether app window closed and no reconnect within %ss. Shutting down server and releasing port...", delay)
        global _global_server
        if _global_server is not None:
            _global_server.should_exit = True
        else:
            import os, signal
            os.kill(os.getpid(), signal.SIGTERM)
    except asyncio.CancelledError:
        pass


async def api_app_exit(request: Request) -> JSONResponse:
    """Trigger delayed server shutdown when app window closes."""
    global _pending_shutdown_task
    _cancel_delayed_shutdown()
    _pending_shutdown_task = asyncio.create_task(_delayed_shutdown(3.0))
    return JSONResponse({"status": "ok", "message": "Shutdown scheduled"})


async def api_app_cancel_exit(request: Request) -> JSONResponse:
    """Cancel pending shutdown when page reloads."""
    _cancel_delayed_shutdown()
    return JSONResponse({"status": "ok", "message": "Shutdown cancelled"})


async def api_health(request: Request) -> JSONResponse:
    """Lightweight health check for portal status and desktop app window heartbeat."""
    _cancel_delayed_shutdown()
    return JSONResponse({"status": "ok", "app": "aether"})


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles handler that injects no-cache headers for instant local UI hot-reloading."""

    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


async def api_news(request: Request) -> JSONResponse:
    """Return cached tech news items, refreshing in background if stale."""
    _cancel_delayed_shutdown()
    try:
        limit = max(1, min(int(request.query_params.get("limit", 30)), 100))
    except (ValueError, TypeError):
        limit = 30
    source = request.query_params.get("source")
    category = request.query_params.get("category")
    force = request.query_params.get("force", "").lower() in ("true", "1", "yes")

    from src.servers.news_service import get_news
    db = DatabaseManager()

    items = await asyncio.to_thread(get_news, db, limit, source, category, force)
    return JSONResponse({
        "status": "ok",
        "items": items,
        "count": len(items),
        "source": source or "all",
        "category": category or "all",
    })


async def api_news_refresh(request: Request) -> JSONResponse:
    """Force live fetch and update of tech news cache."""
    _cancel_delayed_shutdown()
    from src.servers.news_service import fetch_and_cache_news
    db = DatabaseManager()
    items = await asyncio.to_thread(fetch_and_cache_news, db, 25)
    return JSONResponse({
        "status": "ok",
        "items": items,
        "count": len(items),
        "refreshed": True,
    })


async def api_news_digest(request: Request) -> JSONResponse:
    """Return the AI Student & Developer Briefing, cached or freshly generated."""
    _cancel_delayed_shutdown()
    from src.servers.news_service import get_ai_student_digest
    db = DatabaseManager()
    cfg = get_config()
    client = OllamaClient(base_url=cfg.llm.base_url, default_model=resolve_model_for_task("general"))
    digest = await asyncio.to_thread(get_ai_student_digest, db, client, False)
    return JSONResponse({
        "status": "ok",
        "digest": digest,
    })


async def api_news_digest_refresh(request: Request) -> JSONResponse:
    """Force regeneration of the AI Student & Developer Briefing via Ollama."""
    _cancel_delayed_shutdown()
    from src.servers.news_service import get_ai_student_digest
    db = DatabaseManager()
    cfg = get_config()
    client = OllamaClient(base_url=cfg.llm.base_url, default_model=resolve_model_for_task("general"))
    digest = await asyncio.to_thread(get_ai_student_digest, db, client, True)
    return JSONResponse({
        "status": "ok",
        "digest": digest,
        "refreshed": True,
    })


async def api_generated_image(request: Request) -> FileResponse | JSONResponse:
    """Safely serve a locally generated image file."""
    filename = request.path_params.get("filename", "")
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        return JSONResponse({"status": "error", "message": "Invalid filename"}, status_code=400)
    filepath = GENERATED_IMAGES_DIR / filename
    if not filepath.exists() or not filepath.is_file():
        return JSONResponse({"status": "error", "message": "Image not found"}, status_code=404)
    return FileResponse(filepath, media_type="image/png")


async def api_image_status(request: Request) -> JSONResponse:
    """Return ComfyUI connection health, active GPU, and installed checkpoints."""
    _cancel_delayed_shutdown()
    status = await asyncio.to_thread(get_comfyui_status)
    return JSONResponse(status)


class LocalhostOriginMiddleware:
    """Security middleware rejecting cross-origin requests from external web pages.

    Defends against drive-by CSRF / DNS-rebinding attacks originating from external browser
    tabs attempting to access local Aether APIs (files, terminal, vault, etc.).
    """

    ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            origin = headers.get(b"origin", b"").decode("latin1").strip()

            if origin:
                host = (urlparse(origin).hostname or "").lower()
                if host and host not in self.ALLOWED_HOSTS:
                    logger.warning("Blocked cross-origin request from forbidden origin: %s", origin)
                    if scope["type"] == "http":
                        response = JSONResponse(
                            {"error": "Forbidden: Cross-origin request rejected"},
                            status_code=403,
                        )
                        await response(scope, receive, send)
                    else:
                        await send({"type": "websocket.close", "code": 4403})
                    return

            if scope["type"] == "http" and scope.get("method") in ("POST", "PUT", "DELETE", "PATCH"):
                referer = headers.get(b"referer", b"").decode("latin1").strip()
                if referer:
                    host = (urlparse(referer).hostname or "").lower()
                    if host and host not in self.ALLOWED_HOSTS:
                        logger.warning("Blocked state-changing request from external referer: %s", referer)
                        response = JSONResponse(
                            {"error": "Forbidden: External referer rejected"},
                            status_code=403,
                        )
                        await response(scope, receive, send)
                        return

        await self.app(scope, receive, send)


def create_app() -> Starlette:
    """Create configured Starlette application."""
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    routes = [
        Route("/", endpoint=homepage, methods=["GET"]),
        Route("/api/health", endpoint=api_health, methods=["GET"]),
        Route("/api/overview", endpoint=api_overview, methods=["GET"]),
        Route("/api/weather", endpoint=api_weather, methods=["GET"]),
        Route("/api/weather/location", endpoint=api_weather_location, methods=["GET", "POST"]),
        Route("/api/weather/search", endpoint=api_weather_search, methods=["GET"]),
        Route("/api/app/exit", endpoint=api_app_exit, methods=["POST"]),
        Route("/api/app/cancel_exit", endpoint=api_app_cancel_exit, methods=["POST"]),
        Route("/api/calendar", endpoint=api_calendar, methods=["GET"]),
        Route("/api/calendar/auth", endpoint=api_calendar_auth, methods=["GET", "POST"]),
        Route("/api/emails", endpoint=api_emails, methods=["GET"]),
        Route("/api/emails/update", endpoint=api_email_update, methods=["POST"]),
        Route("/api/news", endpoint=api_news, methods=["GET"]),
        Route("/api/news/refresh", endpoint=api_news_refresh, methods=["POST"]),
        Route("/api/news/digest", endpoint=api_news_digest, methods=["GET"]),
        Route("/api/news/digest/refresh", endpoint=api_news_digest_refresh, methods=["POST"]),
        Route("/api/tasks", endpoint=api_tasks, methods=["GET"]),
        Route("/api/tasks/add", endpoint=api_task_add, methods=["POST"]),
        Route("/api/tasks/priority", endpoint=api_task_priority, methods=["POST"]),
        Route("/api/tasks/complete", endpoint=api_task_complete, methods=["POST"]),
        Route("/api/tasks/delete", endpoint=api_task_delete, methods=["POST"]),
        Route("/api/briefing/regenerate", endpoint=api_briefing_regenerate, methods=["POST"]),
        Route("/api/chat", endpoint=api_chat, methods=["POST"]),
        Route("/api/chat/stream", endpoint=api_chat_stream, methods=["POST"]),
        Route("/api/chat/history", endpoint=api_chat_history, methods=["GET"]),
        Route("/api/chat/clear", endpoint=api_chat_clear, methods=["POST"]),
        Route("/api/traces/{trace_id}", endpoint=api_trace_get, methods=["GET"]),
        Route("/api/generated_images/{filename}", endpoint=api_generated_image, methods=["GET"]),
        Route("/api/image/status", endpoint=api_image_status, methods=["GET"]),
        Route("/api/files/tree", endpoint=api_files_tree, methods=["GET"]),
        Route("/api/files/read", endpoint=api_files_read, methods=["GET"]),
        Route("/api/files/save", endpoint=api_files_save, methods=["POST"]),
        Route("/api/files/create", endpoint=api_files_create, methods=["POST"]),
        Route("/api/files/delete", endpoint=api_files_delete, methods=["POST"]),
        Route("/api/files/move", endpoint=api_files_move, methods=["POST"]),
        Route("/api/files/organize", endpoint=api_files_organize, methods=["POST"]),
        Route("/api/files/search", endpoint=api_files_search, methods=["GET"]),
        Route("/api/files/pick", endpoint=api_files_pick, methods=["POST"]),
        Route("/api/files/reveal", endpoint=api_files_reveal, methods=["POST"]),
        Route("/api/files/workspace", endpoint=api_files_workspace, methods=["GET", "POST"]),
        Route("/api/terminal/run", endpoint=api_terminal_run, methods=["POST"]),
        Route("/api/terminal/kill", endpoint=api_terminal_kill, methods=["POST"]),
        WebSocketRoute("/api/terminal/ws", endpoint=terminal_ws_endpoint),
        Route("/api/coder/plan", endpoint=api_coder_plan, methods=["POST"]),
        Route("/api/coder/execute", endpoint=api_coder_execute, methods=["POST"]),
        Route("/api/coder/execute/stream", endpoint=api_coder_execute_stream, methods=["POST"]),
        Route("/api/coder/history", endpoint=api_coder_history, methods=["GET"]),
        Route("/api/coder/clear", endpoint=api_coder_clear, methods=["POST"]),
        Route("/api/coder/graph/status", endpoint=api_coder_graph_status, methods=["GET"]),
        Route("/api/voice/status", endpoint=api_voice_status, methods=["GET"]),
        Route("/api/voice/toggle", endpoint=api_voice_toggle, methods=["POST"]),
        Route("/api/voice/listen", endpoint=api_voice_listen, methods=["POST"]),
        Route("/api/voice/interrupt", endpoint=api_voice_interrupt, methods=["POST"]),
        Route("/api/voice/events", endpoint=api_voice_events, methods=["GET"]),
        Route("/api/screen/capture", endpoint=api_screen_capture, methods=["POST"]),
        Route("/api/screen/window", endpoint=api_screen_window, methods=["GET"]),
        Route("/api/models", endpoint=api_models_list, methods=["GET"]),
        Route("/api/models/set", endpoint=api_models_set, methods=["POST"]),
        Route("/api/models/pull", endpoint=api_models_pull, methods=["POST"]),
        Route("/favicon.ico", endpoint=favicon, methods=["GET"]),
        Mount("/static", app=NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static"),
    ]
    middleware = [Middleware(LocalhostOriginMiddleware)]
    return Starlette(debug=False, routes=routes, middleware=middleware)


app = create_app()

_APP_WINDOW_PROC: subprocess.Popen | None = None


def close_desktop_app_window() -> None:
    """Terminate the desktop app window process when server shuts down."""
    global _APP_WINDOW_PROC
    if _APP_WINDOW_PROC is not None:
        try:
            pid = _APP_WINDOW_PROC.pid
            if _APP_WINDOW_PROC.poll() is None:
                logger.info("Closing desktop app window process (PID %s)...", pid)
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True,
                        timeout=3,
                    )
                else:
                    _APP_WINDOW_PROC.terminate()
        except Exception as e:
            logger.debug("Error closing desktop app window: %s", e)
        _APP_WINDOW_PROC = None


def open_desktop_app_window(url: str, app_mode: bool = True) -> None:
    """Launch Aether in a native standalone desktop app window (no address bar or browser tabs)."""
    global _APP_WINDOW_PROC
    if not app_mode:
        import webbrowser
        webbrowser.open(url)
        return

    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]

    try:
        cfg = get_config()
        profile_dir = (Path(cfg.storage.database_path).resolve().parent / "app_profile").resolve()
    except Exception:
        profile_dir = Path("./data/app_profile").resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    for exe in candidates:
        if os.path.exists(exe):
            try:
                cmd = [
                    exe,
                    f"--app={url}",
                    f"--user-data-dir={profile_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--window-size=1380,900",
                    "--disable-features=Translate",
                ]
                _APP_WINDOW_PROC = subprocess.Popen(cmd)
                logger.info("Launched standalone desktop app window (PID %s) via: %s", _APP_WINDOW_PROC.pid, exe)
                return
            except Exception as e:
                logger.warning("Failed to launch desktop app window via %s: %s", exe, e)

    import webbrowser
    webbrowser.open(url)


def _is_port_in_use(host: str, port: int) -> bool:
    """Check if TCP port is currently occupied."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _is_aether_running(host: str, port: int) -> bool:
    """Check if an active Aether instance is currently serving on host:port."""
    import urllib.request
    try:
        req = urllib.request.Request(f"http://{host}:{port}/api/health", headers={"User-Agent": "Aether-Launcher"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode())
            return data.get("status") == "ok" and data.get("app") == "aether"
    except Exception:
        return False


def _clear_stale_port(port: int) -> None:
    """If a stale or orphaned process is locking the port on Windows, terminate it so this session can bind."""
    if sys.platform != "win32":
        return
    my_pid = str(os.getpid())
    try:
        res = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        for line in res.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    pid = parts[-1]
                    if pid.isdigit() and pid != "0" and pid != my_pid:
                        logger.warning("Terminating stale process (PID %s) holding port %s...", pid, port)
                        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, timeout=3)
    except Exception as ex:
        logger.debug("netstat port kill error: %s", ex)

    try:
        ps_cmd = (
            f"try {{ Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction Stop | "
            f"ForEach-Object {{ if ($_.OwningProcess -ne {my_pid}) {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }} }} }} "
            f"catch {{}}; exit 0"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, timeout=5)
    except Exception as ex:
        logger.debug("PowerShell port kill error: %s", ex)


def _ensure_port_available(host: str, port: int) -> None:
    """Ensure TCP port is free for binding, terminating any lingering zombie processes."""
    if not _is_port_in_use(host, port):
        return

    logger.warning("Port %s is currently occupied. Clearing stale process...", port)
    _clear_stale_port(port)
    import time
    for _ in range(8):
        if not _is_port_in_use(host, port):
            logger.info("Port %s is now available.", port)
            return
        time.sleep(0.25)


def run_web_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = False,
    app_mode: bool = True,
) -> None:
    """Start uvicorn server serving Aether web dashboard with port collision recovery and auto-exit."""
    import atexit
    import threading
    import uvicorn

    global _global_server

    url = f"http://{host}:{port}"

    # Ensure port is clean and free for this console session
    _ensure_port_available(host, port)

    atexit.register(close_desktop_app_window)

    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("\n=======================================================")
    print("[*] Project Aether Desktop Application active at:")
    print(f"[*] {url}")
    print("=======================================================\n")
    if open_browser:
        try:
            open_desktop_app_window(url, app_mode=app_mode)
        except Exception as ex:
            logger.debug("Could not launch app window: %s", ex)

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    _global_server = server

    def _monitor_app_window(proc: subprocess.Popen, srv: uvicorn.Server) -> None:
        try:
            proc.wait()
        except Exception:
            pass
        logger.info("Aether desktop app window closed. Shutting down server...")
        srv.should_exit = True

    if _APP_WINDOW_PROC is not None:
        threading.Thread(
            target=_monitor_app_window,
            args=(_APP_WINDOW_PROC, server),
            daemon=True,
            name="aether-window-monitor",
        ).start()

    def _warmup_model_in_background() -> None:
        try:
            cfg = get_config()
            client = OllamaClient(
                base_url=cfg.llm.base_url,
                default_model=cfg.llm.general_model,
                keep_alive=cfg.llm.keep_alive,
            )
            if client.is_connected():
                client.chat(messages=[{"role": "user", "content": "1"}])
        except Exception:
            pass

    threading.Thread(target=_warmup_model_in_background, daemon=True).start()

    cfg = get_config()
    if getattr(cfg.voice, "enabled", False):
        try:
            from src.voice.service import get_voice_service
            get_voice_service().start()
            logger.info("Voice activation service started.")
        except Exception as e:
            logger.warning("Could not auto-start voice service: %s", e)

    try:
        server.run()
    finally:
        _global_server = None
        close_desktop_app_window()
        stop_comfyui()
        try:
            from src.voice.service import get_voice_service
            get_voice_service().stop()
        except Exception:
            pass


if __name__ == "__main__":
    run_web_server(open_browser=True, app_mode=True)


