"""ReAct execution loop coordinating context, LLM inference, safety gates, and tool dispatch."""
from dataclasses import asdict, dataclass, field
import inspect
import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable, Generator
from typing import Any

from src.agent.context_manager import ContextManager
from src.agent.guardrails import SafetyGuard
from src.agent.prompts import generate_system_prompt
from src.client.ollama_client import OllamaClient

logger = logging.getLogger("aether.loop")

TOOL_DOMAINS: dict[str, set[str]] = {
    "files_and_coding": {
        "files_read_file",
        "files_write_file",
        "files_delete_file",
        "files_patch_file",
        "files_list_directory",
        "files_search_files",
        "files_run_command",
        "files_set_workspace",
        "files_organize_directory",
        "graph_search_symbols",
        "graph_trace_references",
        "graph_get_code_snippet",
        "graph_get_architecture",
    },
    "calendar": {
        "calendar_list_events",
        "calendar_create_event",
        "calendar_create_events",
        "calendar_update_event",
        "calendar_update_events",
        "calendar_delete_event",
        "calendar_get_free_slots",
        "calendar_sync_local_events_to_google",
        "calendar_authenticate_google_calendar",
    },
    "mail": {
        "mail_list_emails",
        "mail_fetch_unread",
        "get_email_details",
        "mail_update_flag",
        "send_email",
        "stage_email_draft",
    },
    "notes": {
        "notes_list_todos",
        "notes_add_todo",
        "notes_complete_todo",
        "notes_update_priority",
        "notes_read_daily",
    },
    "web": {
        "search_web",
        "fetch_web_page",
        "get_weather",
        "get_current_weather",
        "set_weather_location",
    },
    "image_generation": {
        "generate_image",
    },
    "screen_and_vision": {
        "capture_screen",
        "get_active_window",
        "show_aether_dashboard",
    },
}

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "files_and_coding": [
        "file", "files", "folder", "folders", "code", "coding", "function", "class",
        "bug", "fix", "patch", "test", "tests", "pytest", "run", "terminal", "command",
        "repo", "git", "directory", "workspace", "syntax", "python", "javascript",
        "html", "css", "refactor", "lint", "inspect", "diff", "unlink",
        "move to trash", "send to trash", "trash file", "trash folder",
        "delete file", "remove file", "delete folder", "remove folder", "rm",
        "graph", "symbol", "ast", "caller", "callee", "trace", "snippet", "architecture",
        ".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".yaml", ".yml", ".txt", ".sh", ".sql",
    ],
    "calendar": [
        "calendar", "event", "events", "meeting", "meetings", "schedule", "agenda",
        "free slot", "free slots", "free time", "busy", "appointment", "invite",
        "remind me on", "tomorrow", "yesterday", "wednesday", "thursday", "friday",
        "saturday", "sunday", "monday", "tuesday", "noon", "morning", "afternoon",
        "plan", "plans", "plans for today", "plans today", "schedule today", "today's schedule",
        "today's plans", "what do i have today", "what's on today", "what is on today",
        "any plans", "am i free", "free today", "busy today",
        "briefing", "morning briefing", "morning brief", "brief me", "daily briefing",
        "time block", "time blocks", "timeblock", "timeblocks", "timeblocking",
        "block time", "block out", "time slot", "timeslots", "schedule an event",
        "add to calendar", "add event", "tonight",
        "session", "study session", "appointment", "class", "lecture", "call", "sync",
        "standup", "catch-up", "reminder", "hangout", "interview", "webinar", "workshop",
        "lander", "google lander", "gcal", "cal", "google cal", "google calendar",
        "remove event", "delete event", "cancel event", "reschedule", "postpone",
    ],
    "mail": [
        "mail", "email", "emails", "inbox", "unread", "draft", "drafts", "send email",
        "recipient", "sender", "subject", "reply", "compose", "gmail", "outlook",
    ],
    "notes": [
        "todo", "todos", "task", "tasks", "note", "notes", "daily note", "daily review",
        "checklist", "mark as completed", "completed task", "add task", "add todo",
        "shopping", "shopping list", "buy", "groceries", "grocery", "errand", "errands",
        "purchase", "need to buy", "remember to buy", "pick up", "get", "store",
        "chore", "chores", "take out the trash", "trash day",
        "briefing", "morning briefing", "morning brief", "brief me", "daily briefing",
    ],
    "web": [
        "search the web", "search online", "google", "lookup", "browse", "internet",
        "latest news", "weather", "forecast", "temperature", "rain", "snow", "degrees",
        "sunny", "cloudy", "celsius", "fahrenheit", "precipitation",
        "who is", "what is the price", "url", "http", "https",
    ],
    "image_generation": [
        "generate image", "create image", "draw", "generate an image", "picture of",
        "make an image", "paint", "illustration", "sketch", "sdxl", "comfyui", "flux",
        "render an image", "photo of", "generate picture", "draw an image", "image of",
    ],
    "screen_and_vision": [
        "screen", "screens", "screenshot", "screenshots", "display", "monitor",
        "desktop", "window", "windows", "active window", "foreground window",
        "what's on my screen", "what is on my screen", "look at my screen",
        "look my screen", "look my current screen", "look at my current screen",
        "check my screen", "what's on my current screen", "can you see my screen",
        "current screen", "look at this", "see my screen", "read my screen", "what am i looking at",
        "inspect screen", "snap screen", "capture screen", "ocr", "error on screen",
        "show dashboard", "open dashboard", "show app", "open app", "bring window to front",
        "show aether", "open aether",
    ],
}


def detect_intent_domains(query: str) -> set[str]:
    """Detect capability domains relevant to a user query."""
    q_lower = f" {query.lower()} "
    detected: set[str] = set()

    # Automatically identify temporal and schedule time references (e.g. 5pm, 10:30am)
    if re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", q_lower):
        detected.add("calendar")

    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw.startswith(".") or " " in kw:
                if kw in q_lower:
                    detected.add(domain)
                    break
            else:
                if re.search(r"\b" + re.escape(kw) + r"\b", q_lower):
                    detected.add(domain)
                    break

    return detected


def get_tool_domain(tool_name: str) -> str | None:
    """Resolve the capability domain for a tool name."""
    clean_name = tool_name.lower().replace("-", "_")
    for domain, tools in TOOL_DOMAINS.items():
        if clean_name in tools:
            return domain
    return None


def normalize_tool_args(fn_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Normalize common parameter name variants across models and domains."""
    res = dict(args)

    # 1. Files & coding normalization
    if fn_name.startswith("files_") or "file" in fn_name or fn_name in ("runcommand", "terminalcommand"):
        if "path" not in res:
            for k in ("file_path", "filename", "file", "filepath", "target_file", "path_to_file"):
                if k in res:
                    res["path"] = res[k]
                    break
        if "content" not in res:
            for k in ("text", "code", "data", "body"):
                if k in res:
                    res["content"] = res[k]
                    break
        if "command" not in res and "cmd" in res:
            res["command"] = res["cmd"]
        if "target" not in res and "old" in res:
            res["target"] = res["old"]
        if "replacement" not in res and "new" in res:
            res["replacement"] = res["new"]

    # 2. Notes / Todos normalization
    if fn_name.startswith("notes_") or "todo" in fn_name or "note" in fn_name:
        if "text" not in res and "task" not in res:
            for k in ("tasks", "items", "todo", "todos", "item", "description", "title"):
                if k in res:
                    res["text"] = res[k]
                    break

    # 3. Calendar normalization
    if (
        fn_name.startswith("calendar_")
        or "calendar" in fn_name
        or any(k in fn_name for k in ("event", "events", "freeslot", "free_slot"))
    ):
        if "title" not in res:
            for k in ("summary", "name", "event", "task", "activity", "text", "event_title", "subject", "title_str"):
                if k in res:
                    res["title"] = res[k]
                    break
        if "start_iso" not in res:
            for k in ("start", "start_time", "startTime", "start_date", "start_dt", "datetime", "timestamp"):
                if k in res:
                    res["start_iso"] = res[k]
                    break
        d_val = res.get("date") or res.get("date_str") or res.get("day") or res.get("date_iso")
        t_val = res.get("time") or res.get("time_str") or res.get("hour")
        if "start_iso" not in res:
            if d_val and t_val:
                res["start_iso"] = f"{d_val} {t_val}"
            elif d_val:
                res["start_iso"] = str(d_val)
            elif t_val:
                res["start_iso"] = str(t_val)
        elif t_val and (res["start_iso"] == d_val or not any(k in str(res["start_iso"]).lower() for k in (":", "am", "pm"))):
            res["start_iso"] = f"{res['start_iso']} {t_val}"

        if "end_iso" not in res:
            for k in ("end", "end_time", "endTime", "end_date", "end_dt", "end_datetime"):
                if k in res:
                    res["end_iso"] = res[k]
                    break
        if "date" not in res and d_val:
            res["date"] = d_val
        if "duration_minutes" not in res and "duration" in res:
            res["duration_minutes"] = res["duration"]
        # Clean up keys that conflict with create_event / update_event
        res.pop("content", None)
        if "title" in res:
            res.pop("text", None)

    return res


@dataclass
class StepTrace:
    step: int
    type: str  # "inference", "tool_call", "synthesis"
    name: str = ""
    latency_ms: float = 0.0
    tokens: int = 0
    status: str = "ok"  # "ok", "error", "cancelled"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionTrace:
    trace_id: str
    total_latency_ms: float
    total_tokens: int
    step_count: int
    model: str
    steps: list[StepTrace] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentLoop:
    """Deterministic ReAct tool-calling loop for local desktop automation."""

    def __init__(
        self,
        model: str = "qwen2.5:7b-instruct",
        client: OllamaClient | None = None,
        guard: SafetyGuard | None = None,
        max_steps: int = 25,
        custom_instructions: str | None = None,
        context_manager: ContextManager | None = None,
        dynamic_tool_masking: bool = True,
    ) -> None:
        self.model = model
        self.base_model = model
        self.client = client or OllamaClient(default_model=model)
        self.guard = guard or SafetyGuard()
        self.max_steps = max_steps
        self.custom_instructions = custom_instructions
        self.context_manager = context_manager or ContextManager()
        self.dynamic_tool_masking = dynamic_tool_masking

        self.tools_schema: list[dict[str, Any]] = []
        self.tool_dispatch: dict[str, Callable[..., Any]] = {}
        self.messages: list[dict[str, Any]] = []
        self.last_trace: ExecutionTrace | None = None

    def _finalize_trace(
        self,
        trace_id: str,
        t_start: float,
        step_traces: list[StepTrace],
        steps: int,
    ) -> ExecutionTrace:
        """Compile and cache structured telemetry for this execution trajectory."""
        total_lat = round((time.perf_counter() - t_start) * 1000, 1)
        tot_tok = sum(s.tokens for s in step_traces)
        trace = ExecutionTrace(
            trace_id=trace_id,
            total_latency_ms=total_lat,
            total_tokens=tot_tok,
            step_count=steps,
            model=self.model,
            steps=step_traces,
        )
        self.last_trace = trace
        return trace

    def get_active_tools_schema(
        self,
        user_input: str,
        active_domains: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Prune tools schema based on detected intent domains to save tokens and avoid hallucinations."""
        if not self.dynamic_tool_masking or not self.tools_schema:
            return self.tools_schema

        intent_domains = detect_intent_domains(user_input)
        combined_domains = set(intent_domains)
        if active_domains:
            combined_domains.update(active_domains)

        # Context-aware retention: inspect recent conversation history (last 4 messages)
        # If the recent dialogue discussed calendar, mail, notes, or files, retain those domains
        if hasattr(self, "messages") and self.messages:
            for past_m in self.messages[-4:]:
                content = str(past_m.get("content", "") or "")
                if content:
                    combined_domains.update(detect_intent_domains(content))
                if past_m.get("role") == "tool":
                    tool_dom = get_tool_domain(str(past_m.get("name", "")))
                    if tool_dom:
                        combined_domains.add(tool_dom)

        # If no specific domain detected, keep all tools
        if not combined_domains:
            return self.tools_schema

        allowed_names: set[str] = set()
        for dom in combined_domains:
            allowed_names.update(TOOL_DOMAINS.get(dom, set()))

        all_classified = set().union(*TOOL_DOMAINS.values())

        filtered_schema: list[dict[str, Any]] = []
        for tool_def in self.tools_schema:
            fn_name = tool_def.get("function", {}).get("name", "")
            if fn_name not in all_classified or fn_name in allowed_names:
                filtered_schema.append(tool_def)

        if not filtered_schema:
            return self.tools_schema

        logger.debug(
            "Dynamic tool masking: %d -> %d tools for domains %s",
            len(self.tools_schema),
            len(filtered_schema),
            combined_domains,
        )
        return filtered_schema

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        func: Callable[..., Any],
        safe: bool = True,
    ) -> None:
        """Register a callable tool with its schema definition and safety classification."""
        self.tools_schema.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        })
        self.tool_dispatch[name] = func
        self.guard.register_tool(name, safe=safe)
        logger.info("Registered tool %s (safe=%s)", name, safe)

    def reset_conversation(self) -> None:
        """Clear the conversational memory."""
        self.messages = []

    def _invoke_tool_safely(
        self,
        func: Callable[..., Any],
        fn_name: str,
        args: dict[str, Any],
    ) -> tuple[Any, bool]:
        """Execute a tool with signature inspection, pruning unrecognized hallucinated kwargs."""
        is_err = False
        try:
            sig = inspect.signature(func)
            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if not has_var_kw:
                filtered_args = {k: v for k, v in args.items() if k in sig.parameters}
                if len(filtered_args) < len(args):
                    dropped = set(args.keys()) - set(filtered_args.keys())
                    logger.debug("Pruned unrecognized arguments for tool '%s': %s", fn_name, dropped)
            else:
                filtered_args = args

            res = func(**filtered_args)
            if isinstance(res, dict) and res.get("status") == "error":
                is_err = True
            return res, is_err
        except Exception as ex:
            logger.error("Error executing tool %s: %s", fn_name, ex)
            return {"status": "error", "message": f"Execution error in '{fn_name}': {ex}"}, True

    def _resolve_tool_name(self, name: str) -> str | None:
        """Fuzzily resolve tool names, accommodating missing underscores, case differences, and aliases common in 7B models."""
        if not name or not isinstance(name, str):
            return None

        clean_name = name.strip().strip("'\"`")
        if clean_name.endswith("()"):
            clean_name = clean_name[:-2].strip()
        clean_name = re.sub(r"^(?:functions?|tools?|api|default_api)[\.:_]+", "", clean_name, flags=re.IGNORECASE)

        if clean_name in self.tool_dispatch:
            return clean_name

        clean_target = re.sub(r"[^a-zA-Z0-9]", "", clean_name).lower()
        if not clean_target:
            return None

        # 1. Exact match ignoring underscores, hyphens, and case
        for registered in self.tool_dispatch:
            if re.sub(r"[^a-zA-Z0-9]", "", registered).lower() == clean_target:
                return registered

        # 2. Common aliases generated by smaller local models
        aliases: dict[str, str] = {
            "fileslistfiles": "files_list_directory",
            "listfiles": "files_list_directory",
            "listdirectory": "files_list_directory",
            "fileslist": "files_list_directory",
            "filestree": "files_list_directory",
            "setworkspace": "files_set_workspace",
            "changeworkspace": "files_set_workspace",
            "switchworkspace": "files_set_workspace",
            "filessetworkspace": "files_set_workspace",
            "readfile": "files_read_file",
            "filesreadfile": "files_read_file",
            "writefile": "files_write_file",
            "fileswritefile": "files_write_file",
            "createfile": "files_write_file",
            "newfile": "files_write_file",
            "filescreatefile": "files_write_file",
            "filesnewfile": "files_write_file",
            "maketextfile": "files_write_file",
            "write": "files_write_file",
            "deletefile": "files_delete_file",
            "delete_file": "files_delete_file",
            "filesdeletefile": "files_delete_file",
            "files_delete": "files_delete_file",
            "removefile": "files_delete_file",
            "filesremovefile": "files_delete_file",
            "patchfile": "files_patch_file",
            "filespatchfile": "files_patch_file",
            "searchfiles": "files_search_files",
            "filesearchfiles": "files_search_files",
            "runcommand": "files_run_command",
            "terminalcommand": "files_run_command",
            "filesruncommand": "files_run_command",
            "executeterminalcommand": "files_run_command",
            "organizedirectory": "files_organize_directory",
            "listtodos": "notes_list_todos",
            "addtodo": "notes_add_todo",
            "completetodo": "notes_complete_todo",
            "updatepriority": "notes_update_priority",
            "setpriority": "notes_update_priority",
            "noteslisttodos": "notes_list_todos",
            "notesaddtodo": "notes_add_todo",
            "notescompletetodo": "notes_complete_todo",
            "notesupdatepriority": "notes_update_priority",
            "notessetpriority": "notes_update_priority",
            "notesreaddaily": "notes_read_daily",
            "readdailynote": "notes_read_daily",
            "listevents": "calendar_list_events",
            "calendarlistevents": "calendar_list_events",
            "createevent": "calendar_create_event",
            "calendarcreateevent": "calendar_create_event",
            "createevents": "calendar_create_events",
            "calendarcreateevents": "calendar_create_events",
            "calendaraddevents": "calendar_create_events",
            "calendar_add_events": "calendar_create_events",
            "calendar_create_events": "calendar_create_events",
            "addevents": "calendar_create_events",
            "batchcreateevents": "calendar_create_events",
            "getfreeslots": "calendar_get_free_slots",
            "calendargetfreeslots": "calendar_get_free_slots",
            "sendemail": "send_email",
            "stageemail": "stage_email_draft",
            "listemails": "mail_list_emails",
            "fetchunreademails": "mail_fetch_unread",
            "mailfetchunread": "mail_fetch_unread",
            "searchweb": "search_web",
            "websearch": "search_web",
            "searchinternet": "search_web",
            "duckduckgo": "search_web",
            "googlesearch": "search_web",
            "fetchwebpage": "fetch_web_page",
            "fetchpage": "fetch_web_page",
            "fetchurl": "fetch_web_page",
            "getwebpage": "fetch_web_page",
            "readwebpage": "fetch_web_page",
            "writefile": "files_write_file",
            "fileswritefile": "files_write_file",
            "patchfile": "files_patch_file",
            "filespatchfile": "files_patch_file",
            "readfile": "files_read_file",
            "filesreadfile": "files_read_file",
            "listdirectory": "files_list_directory",
            "fileslistdirectory": "files_list_directory",
            "runcommand": "files_run_command",
            "filesruncommand": "files_run_command",
            "generateimage": "generate_image",
            "imagegenerate": "generate_image",
            "drawimage": "generate_image",
            "createimage": "generate_image",
            "text2image": "generate_image",
            "searchfiles": "files_search_files",
            "filessearchfiles": "files_search_files",
        }
        if clean_target in aliases:
            target = aliases[clean_target]
            if target in self.tool_dispatch:
                return target
            for prefix in ("calendar_", "notes_", "mail_", "files_"):
                if target.startswith(prefix) and target[len(prefix):] in self.tool_dispatch:
                    return target[len(prefix):]
                if f"{prefix}{target}" in self.tool_dispatch:
                    return f"{prefix}{target}"

        # 3. Check suffix / containment match comparing normalized strings (e.g. model emitted "listtodos" or "list_directory")
        for registered in self.tool_dispatch:
            reg_clean = re.sub(r"[^a-zA-Z0-9]", "", registered).lower()
            if reg_clean and (reg_clean.endswith(clean_target) or clean_target.endswith(reg_clean)):
                return registered

        return None

    def _extract_json_tool_calls(self, text: str) -> list[dict[str, Any]]:
        """Extract valid tool call JSON dicts from freeform text or code blocks using JSONDecoder."""
        if not text:
            return []
        decoder = json.JSONDecoder()
        results: list[dict[str, Any]] = []
        pos = 0
        while pos < len(text):
            idx = text.find("{", pos)
            if idx == -1:
                break
            try:
                obj, end = decoder.raw_decode(text[idx:])
                if isinstance(obj, dict) and "name" in obj:
                    results.append(obj)
                pos = idx + max(end, 1)
            except json.JSONDecodeError:
                pos = idx + 1
        return results

    def _sanitize_final_content(self, text: str) -> str:
        """Strip any leaked <tool_call> or <think> XML tags from final conversational text."""
        if not text:
            return ""
        # Strip <think>...</think>
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
        # Strip <tool_call>...</tool_call>
        cleaned = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"</?tool_call>", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE).strip()
        if not cleaned and ("tool_call" in text.lower() or "arguments" in text.lower()):
            return "I have processed and executed that action for you."
        return cleaned or text

    def run_turn(
        self,
        user_input: str,
        images: list[str] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Execute a full conversation turn with the user, handling multi-step tool calls and multimodal images."""
        trace_id = f"tr_{uuid.uuid4().hex[:8]}"
        t_start = time.perf_counter()
        step_traces: list[StepTrace] = []

        # Reset model back to base model if previous turn was vision/multimodal
        if not images and hasattr(self, "base_model") and self.model != self.base_model:
            self.model = self.base_model
            if self.client:
                self.client.default_model = self.base_model

        # Ensure fresh temporal grounding on each turn if starting or update system prompt
        system_prompt = generate_system_prompt(self.custom_instructions)

        if not self.messages or self.messages[0].get("role") != "system":
            self.messages.insert(0, {"role": "system", "content": system_prompt})
        else:
            # Refresh system prompt with active ground-truth timestamp
            self.messages[0]["content"] = system_prompt

        user_msg: dict[str, Any] = {"role": "user", "content": user_input}
        if images:
            user_msg["images"] = list(images)
        self.messages.append(user_msg)
        invoked_web_sources: list[dict[str, str]] = []
        invoked_tool_domains: set[str] = set()
        consecutive_tool_errors: int = 0
        last_failed_tool: str = ""

        steps = 0
        while steps < self.max_steps:
            if cancel_event and cancel_event.is_set():
                logger.info("AgentLoop turn cancelled by external event.")
                self._finalize_trace(trace_id, t_start, step_traces, steps)
                return "Action was cancelled."

            steps += 1
            logger.debug("ReAct step %d for input: %s", steps, user_input[:50])
            step_t0 = time.perf_counter()

            try:
                if cancel_event and cancel_event.is_set():
                    self._finalize_trace(trace_id, t_start, step_traces, steps)
                    return "Action was cancelled."
                is_vision_model = any(k in (self.model or "").lower() for k in ("vl", "vision", "llava", "moondream", "minicpm"))
                prepared_messages = self.context_manager.prepare_messages(self.messages, model=self.model)
                if not is_vision_model:
                    prepared_messages = [{k: v for k, v in m.items() if k != "images"} for m in prepared_messages]

                active_tools = (
                    self.get_active_tools_schema(user_input, active_domains=invoked_tool_domains)
                    if self.tools_schema and not images and not is_vision_model
                    else None
                )
                response_msg = self.client.chat(
                    messages=prepared_messages,
                    tools=active_tools,
                    model=self.model,
                )
            except Exception as e:
                err_str = str(e)
                if "multimodal" in err_str.lower() or "does not support tools" in err_str.lower():
                    logger.warning("Retrying inference without multimodal payloads or tools due to model mismatch: %s", e)
                    try:
                        clean_msgs = [{k: v for k, v in m.items() if k != "images"} for m in prepared_messages]
                        response_msg = self.client.chat(
                            messages=clean_msgs,
                            tools=None,
                            model=self.model,
                        )
                    except Exception as retry_err:
                        logger.error("Inference retry failed: %s", retry_err)
                        self._finalize_trace(trace_id, t_start, step_traces, steps)
                        return f"Error during model inference: {retry_err}"
                else:
                    logger.error("Inference failed: %s", e)
                    self._finalize_trace(trace_id, t_start, step_traces, steps)
                    return f"Error during model inference: {e}"

            inf_latency = round((time.perf_counter() - step_t0) * 1000, 1)
            p_toks = sum(len(str(m.get("content", ""))) // 4 for m in prepared_messages)
            r_toks = len(str(response_msg.get("content") or "")) // 4
            step_traces.append(StepTrace(
                step=steps,
                type="inference",
                name=self.model,
                latency_ms=inf_latency,
                tokens=p_toks + r_toks,
                status="ok",
            ))

            tool_calls = response_msg.get("tool_calls") or []

            if not tool_calls:
                content_raw = (response_msg.get("content") or "").strip()
                extracted = self._extract_json_tool_calls(content_raw)
                for parsed in extracted:
                    fn_name = str(parsed.get("name", "")).strip()
                    resolved_name = self._resolve_tool_name(fn_name)
                    fn_args = (
                        parsed.get("arguments")
                        or parsed.get("parameters")
                        or parsed.get("args")
                        or parsed.get("input")
                        or {}
                    )
                    if isinstance(fn_args, str):
                        try:
                            fn_args = json.loads(fn_args)
                        except Exception:
                            fn_args = {}

                    actual_tool = resolved_name or fn_name
                    tool_calls.append({
                        "id": f"call_{steps}_{actual_tool}",
                        "function": {"name": actual_tool, "arguments": fn_args if isinstance(fn_args, dict) else {}},
                    })
                    if resolved_name:
                        logger.info("Parsed and resolved inline tool call: %s -> %s", fn_name, resolved_name)
                    else:
                        logger.warning("Parsed unrecognized inline tool call '%s'; routing through safety dispatcher for model feedback.", fn_name)

                if tool_calls:
                    response_msg["tool_calls"] = tool_calls
                    response_msg["content"] = None

            # If no tool calls requested, model has returned its final textual answer
            if not tool_calls:
                final_content = (response_msg.get("content") or "").strip()

                if not final_content and self.tools_schema:
                    # Model returned empty string with tools enabled; retry once as direct text completion
                    logger.debug("Model returned empty content with tools schema; falling back to plain chat.")
                    try:
                        fallback_msg = self.client.chat(
                            messages=prepared_messages,
                            tools=None,
                            model=self.model,
                        )
                        final_content = (fallback_msg.get("content") or "").strip()
                    except Exception as ex:
                        logger.warning("Direct chat fallback failed: %s", ex)

                final_content = self._sanitize_final_content(final_content)

                if not final_content:
                    final_content = "I have processed your request. How else can I assist you?"

                # Ensure source links are embedded at the end whenever web tools were used
                if invoked_web_sources:
                    if "**Source" not in final_content and "**Sources" not in final_content:
                        sources_lines = [f"- [{s['title']}]({s['url']})" for s in invoked_web_sources[:3]]
                        final_content = final_content.rstrip() + "\n\n**Sources:**\n" + "\n".join(sources_lines)

                # Sanitize any hallucinated hostname or protocol preceding generated images
                final_content = re.sub(r"https?://[^\s\)]*?/api/generated_images/", "/api/generated_images/", final_content)

                self.messages.append({"role": "assistant", "content": final_content})
                self._finalize_trace(trace_id, t_start, step_traces, steps)
                return final_content

            # Record assistant message with tool calls in history
            self.messages.append(response_msg)

            # Process all tool calls in this step
            for tool_call in tool_calls:
                fn_info = tool_call.get("function", {})
                raw_fn_name = fn_info.get("name") or ""
                fn_name = self._resolve_tool_name(raw_fn_name) or raw_fn_name
                dom = get_tool_domain(fn_name)
                if dom:
                    invoked_tool_domains.add(dom)
                raw_args = (
                    fn_info.get("arguments")
                    or fn_info.get("parameters")
                    or fn_info.get("args")
                    or fn_info.get("input")
                    or {}
                )

                # Parse arguments if returned as JSON string
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = dict(raw_args) if isinstance(raw_args, dict) else {}

                args = normalize_tool_args(fn_name, args)

                tool_t0 = time.perf_counter()
                is_err = False
                if fn_name not in self.tool_dispatch:
                    is_err = True
                    tool_output = json.dumps({
                        "status": "error",
                        "message": f"Tool '{fn_name}' is not recognized.",
                    })
                else:
                    # Evaluate safety gate
                    authorized, cancel_payload = self.guard.check_and_authorize(fn_name, args)
                    if not authorized:
                        tool_output = cancel_payload or "Action cancelled by user."
                    else:
                        func = self.tool_dispatch[fn_name]
                        res, is_err = self._invoke_tool_safely(func, fn_name, args)
                        if fn_name == "capture_screen" and isinstance(res, dict):
                            clean_res = {k: v for k, v in res.items() if k not in ("image_base64", "data_url")}
                            tool_output = json.dumps(clean_res)
                        else:
                            tool_output = json.dumps(res) if isinstance(res, (dict, list)) else str(res)

                        if not is_err:
                            # Record web sources if search/fetch tool was executed
                            if fn_name in ("search_web", "websearch", "searchinternet", "duckduckgo", "googlesearch"):
                                for m in re.finditer(r"\[(.*?)\]\(((?:https?|file):\/\/[^\s\)]+)\)", str(tool_output)):
                                    t = m.group(1).strip()
                                    u = m.group(2).strip()
                                    if u and not any(s["url"] == u for s in invoked_web_sources):
                                        invoked_web_sources.append({"title": t or "Source", "url": u})
                            elif fn_name in ("fetch_web_page", "fetchpage", "fetchurl", "getwebpage", "readwebpage"):
                                target_url = args.get("url", "").strip()
                                if target_url and not any(s["url"] == target_url for s in invoked_web_sources):
                                    from urllib.parse import urlparse
                                    host = urlparse(target_url).netloc or "Web Page"
                                    invoked_web_sources.append({"title": host, "url": target_url})

                tool_lat = round((time.perf_counter() - tool_t0) * 1000, 1)
                step_traces.append(StepTrace(
                    step=steps,
                    type="tool_call",
                    name=fn_name,
                    latency_ms=tool_lat,
                    tokens=len(str(tool_output)) // 4,
                    status="error" if is_err else ("cancelled" if (fn_name in self.tool_dispatch and not authorized) else "ok"),
                    details={"args_keys": list(args.keys())},
                ))

                if is_err:
                    if last_failed_tool == fn_name:
                        consecutive_tool_errors += 1
                    else:
                        consecutive_tool_errors = 1
                        last_failed_tool = fn_name
                else:
                    consecutive_tool_errors = 0
                    last_failed_tool = ""

                if fn_name == "capture_screen" and isinstance(res, dict) and res.get("image_base64"):
                    if self.messages:
                        for m in reversed(self.messages):
                            if m.get("role") == "user":
                                m.setdefault("images", []).append(res["image_base64"])
                                break
                    try:
                        from src.config import get_config
                        cfg = get_config()
                        vis_model = getattr(cfg.llm, "vision_model", "qwen2.5vl:7b")
                        if vis_model:
                            self.model = vis_model
                            if self.client:
                                self.client.default_model = vis_model
                    except Exception:
                        pass

                # Compress payload to prevent context window exhaustion (higher budget for code, directory, note, and calendar reads)
                tool_budget = 12000 if fn_name in (
                    "files_read_file", "files_search_files", "files_list_directory",
                    "files_patch_file", "files_run_command", "files_set_workspace",
                    "notes_read_daily", "read_project_notes", "notes_list_todos",
                    "calendar_list_events",
                ) else None
                safe_output = self.context_manager.compress_tool_result(str(tool_output), max_chars=tool_budget)

                # Append tool observation back to conversation history
                self.messages.append({
                    "role": "tool",
                    "name": fn_name,
                    "content": safe_output,
                })

            if consecutive_tool_errors >= 2:
                logger.warning("Aborting ReAct loop: tool '%s' failed %d consecutive times.", last_failed_tool, consecutive_tool_errors)
                abort_msg = f"I encountered repeated errors attempting to execute '{last_failed_tool}'. Please verify the parameters."
                self.messages.append({"role": "assistant", "content": abort_msg})
                self._finalize_trace(trace_id, t_start, step_traces, steps)
                return abort_msg

        # Exceeded step limit - attempt a final wrap-up answer summarizing actions taken
        fallback_msg = f"Agent reached the maximum tool execution limit ({self.max_steps} steps) without completing."
        try:
            summary_messages = self.context_manager.prepare_messages(self.messages)
            summary_messages.append({
                "role": "user",
                "content": "Please provide a concise final summary of all actions completed so far and their results.",
            })
            summary_resp = self.client.chat(messages=summary_messages, tools=None, model=self.model)
            summary_text = (summary_resp.get("content") or "").strip()
            if summary_text:
                fallback_msg = summary_text
        except Exception:
            pass

        if invoked_web_sources and "**Source" not in fallback_msg and "**Sources" not in fallback_msg:
            sources_lines = [f"- [{s['title']}]({s['url']})" for s in invoked_web_sources[:3]]
            fallback_msg = fallback_msg.rstrip() + "\n\n**Sources:**\n" + "\n".join(sources_lines)
        self.messages.append({"role": "assistant", "content": fallback_msg})
        self._finalize_trace(trace_id, t_start, step_traces, steps)
        return fallback_msg

    def run_turn_stream(
        self,
        user_input: str,
        images: list[str] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        # Reset model back to base model if previous turn was vision/multimodal
        if not images and hasattr(self, "base_model") and self.model != self.base_model:
            self.model = self.base_model
            if self.client:
                self.client.default_model = self.base_model

        system_prompt = generate_system_prompt(self.custom_instructions)

        if not self.messages or self.messages[0].get("role") != "system":
            self.messages.insert(0, {"role": "system", "content": system_prompt})
        else:
            self.messages[0]["content"] = system_prompt

        user_msg: dict[str, Any] = {"role": "user", "content": user_input}
        if images:
            user_msg["images"] = list(images)
        self.messages.append(user_msg)
        invoked_web_sources: list[dict[str, str]] = []
        invoked_tool_domains: set[str] = set()
        consecutive_tool_errors: int = 0
        last_failed_tool: str = ""

        trace_id = f"tr_{uuid.uuid4().hex[:8]}"
        t_start = time.perf_counter()
        step_traces: list[StepTrace] = []

        steps = 0
        while steps < self.max_steps:
            steps += 1
            logger.debug("ReAct stream step %d for input: %s", steps, user_input[:50])
            step_t0 = time.perf_counter()

            try:
                is_vision_model = any(k in (self.model or "").lower() for k in ("vl", "vision", "llava", "moondream", "minicpm"))
                prepared_messages = self.context_manager.prepare_messages(self.messages, model=self.model)
                if not is_vision_model:
                    prepared_messages = [{k: v for k, v in m.items() if k != "images"} for m in prepared_messages]

                active_tools = (
                    self.get_active_tools_schema(user_input, active_domains=invoked_tool_domains)
                    if self.tools_schema and not images and not is_vision_model
                    else None
                )

                streamed_tokens: list[str] = []
                accumulated_tool_calls: list[dict[str, Any]] = []
                response_msg: dict[str, Any] = {}

                for chunk_ev in self.client.chat_stream(
                    messages=prepared_messages,
                    tools=active_tools,
                    model=self.model,
                ):
                    ev_type = chunk_ev.get("type")
                    if ev_type == "token":
                        delta = chunk_ev.get("delta", "")
                        streamed_tokens.append(delta)
                        full_so_far = "".join(streamed_tokens)
                        is_tool_or_think = "<tool_call" in full_so_far or "<think" in full_so_far
                        if not accumulated_tool_calls and not is_tool_or_think:
                            yield {"type": "token", "delta": delta}
                    elif ev_type == "tool_calls":
                        t_calls = chunk_ev.get("tool_calls") or []
                        accumulated_tool_calls.extend(t_calls)
                    elif ev_type == "done":
                        response_msg = chunk_ev.get("message", {})
                        if not accumulated_tool_calls and response_msg.get("tool_calls"):
                            accumulated_tool_calls.extend(response_msg.get("tool_calls"))

            except Exception as e:
                err_str = str(e)
                logger.error("Inference stream error: %s", err_str)
                self._finalize_trace(trace_id, t_start, step_traces, steps)
                yield {"type": "error", "message": f"Error during model inference: {err_str}"}
                return

            inf_latency = round((time.perf_counter() - step_t0) * 1000, 1)
            p_toks = sum(len(str(m.get("content", ""))) // 4 for m in prepared_messages)
            r_toks = len("".join(streamed_tokens)) // 4
            step_traces.append(StepTrace(
                step=steps,
                type="inference",
                name=self.model,
                latency_ms=inf_latency,
                tokens=p_toks + r_toks,
                status="ok",
            ))

            tool_calls = accumulated_tool_calls or response_msg.get("tool_calls") or []

            if not tool_calls:
                content_raw = "".join(streamed_tokens).strip()
                extracted = self._extract_json_tool_calls(content_raw)
                for parsed in extracted:
                    fn_name = str(parsed.get("name", "")).strip()
                    resolved_name = self._resolve_tool_name(fn_name)
                    fn_args = (
                        parsed.get("arguments")
                        or parsed.get("parameters")
                        or parsed.get("args")
                        or parsed.get("input")
                        or {}
                    )
                    if isinstance(fn_args, str):
                        try:
                            fn_args = json.loads(fn_args)
                        except Exception:
                            fn_args = {}
                    actual_tool = resolved_name or fn_name
                    tool_calls.append({
                        "id": f"call_{steps}_{actual_tool}",
                        "function": {"name": actual_tool, "arguments": fn_args if isinstance(fn_args, dict) else {}},
                    })
                if tool_calls:
                    yield {"type": "clear_tokens"}

            if not tool_calls:
                final_content = "".join(streamed_tokens).strip()
                final_content = self._sanitize_final_content(final_content)
                if not final_content:
                    final_content = "I have processed your request. How else can I assist you?"
                    yield {"type": "token", "delta": final_content}

                if invoked_web_sources:
                    if "**Source" not in final_content and "**Sources" not in final_content:
                        sources_lines = [f"- [{s['title']}]({s['url']})" for s in invoked_web_sources[:3]]
                        sources_block = "\n\n**Sources:**\n" + "\n".join(sources_lines)
                        final_content = final_content.rstrip() + sources_block
                        yield {"type": "token", "delta": sources_block}

                final_content = re.sub(r"https?://[^\s\)]*?/api/generated_images/", "/api/generated_images/", final_content)
                self.messages.append({"role": "assistant", "content": final_content})
                trace = self._finalize_trace(trace_id, t_start, step_traces, steps)
                yield {
                    "type": "done",
                    "full_text": final_content,
                    "model": self.model,
                    "trace": trace.to_dict(),
                }
                return

            self.messages.append({
                "role": "assistant",
                "tool_calls": tool_calls,
            })

            for tool_call in tool_calls:
                fn_info = tool_call.get("function", {})
                raw_fn_name = fn_info.get("name") or ""
                fn_name = self._resolve_tool_name(raw_fn_name) or raw_fn_name
                dom = get_tool_domain(fn_name)
                if dom:
                    invoked_tool_domains.add(dom)

                raw_args = (
                    fn_info.get("arguments")
                    or fn_info.get("parameters")
                    or fn_info.get("args")
                    or fn_info.get("input")
                    or {}
                )
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = dict(raw_args) if isinstance(raw_args, dict) else {}

                args = normalize_tool_args(fn_name, args)

                yield {"type": "tool_start", "tool": fn_name, "args": args}

                tool_t0 = time.perf_counter()
                is_err = False
                if fn_name not in self.tool_dispatch:
                    is_err = True
                    tool_output = json.dumps({
                        "status": "error",
                        "message": f"Tool '{fn_name}' is not recognized.",
                    })
                else:
                    authorized, cancel_payload = self.guard.check_and_authorize(fn_name, args)
                    if not authorized:
                        tool_output = cancel_payload or "Action cancelled by user."
                    else:
                        func = self.tool_dispatch[fn_name]
                        res, is_err = self._invoke_tool_safely(func, fn_name, args)
                        if fn_name == "capture_screen" and isinstance(res, dict):
                            clean_res = {k: v for k, v in res.items() if k not in ("image_base64", "data_url")}
                            tool_output = json.dumps(clean_res)
                        else:
                            tool_output = json.dumps(res) if isinstance(res, (dict, list)) else str(res)

                        if not is_err:
                            if fn_name in ("search_web", "websearch", "searchinternet", "duckduckgo", "googlesearch"):
                                for m in re.finditer(r"\[(.*?)\]\(((?:https?|file):\/\/[^\s\)]+)\)", str(tool_output)):
                                    t = m.group(1).strip()
                                    u = m.group(2).strip()
                                    if u and not any(s["url"] == u for s in invoked_web_sources):
                                        invoked_web_sources.append({"title": t or "Source", "url": u})
                            elif fn_name in ("fetch_web_page", "fetchpage", "fetchurl", "getwebpage", "readwebpage"):
                                target_url = args.get("url", "").strip()
                                if target_url and not any(s["url"] == target_url for s in invoked_web_sources):
                                    from urllib.parse import urlparse
                                    host = urlparse(target_url).netloc or "Web Page"
                                    invoked_web_sources.append({"title": host, "url": target_url})

                tool_lat = round((time.perf_counter() - tool_t0) * 1000, 1)
                step_traces.append(StepTrace(
                    step=steps,
                    type="tool_call",
                    name=fn_name,
                    latency_ms=tool_lat,
                    tokens=len(str(tool_output)) // 4,
                    status="error" if is_err else ("cancelled" if (fn_name in self.tool_dispatch and not authorized) else "ok"),
                    details={"args_keys": list(args.keys())},
                ))

                if is_err:
                    if last_failed_tool == fn_name:
                        consecutive_tool_errors += 1
                    else:
                        consecutive_tool_errors = 1
                        last_failed_tool = fn_name
                else:
                    consecutive_tool_errors = 0
                    last_failed_tool = ""

                preview = str(tool_output)
                if len(preview) > 120:
                    preview = preview[:117] + "..."
                yield {"type": "tool_end", "tool": fn_name, "preview": preview}

                if fn_name == "capture_screen" and isinstance(res, dict) and res.get("image_base64"):
                    if self.messages:
                        for m in reversed(self.messages):
                            if m.get("role") == "user":
                                m.setdefault("images", []).append(res["image_base64"])
                                break
                    try:
                        from src.config import get_config
                        cfg = get_config()
                        vis_model = getattr(cfg.llm, "vision_model", "qwen2.5vl:7b")
                        if vis_model:
                            self.model = vis_model
                            if self.client:
                                self.client.default_model = vis_model
                    except Exception:
                        pass

                tool_budget = 12000 if fn_name in (
                    "files_read_file", "files_search_files", "files_list_directory",
                    "files_patch_file", "files_run_command", "files_set_workspace",
                    "notes_read_daily", "read_project_notes", "notes_list_todos",
                    "calendar_list_events",
                ) else None
                safe_output = self.context_manager.compress_tool_result(str(tool_output), max_chars=tool_budget)

                self.messages.append({
                    "role": "tool",
                    "name": fn_name,
                    "content": safe_output,
                })

            if consecutive_tool_errors >= 2:
                logger.warning("Aborting ReAct stream: tool '%s' failed %d consecutive times.", last_failed_tool, consecutive_tool_errors)
                abort_msg = f"I encountered repeated errors attempting to execute '{last_failed_tool}'. Please verify the parameters."
                self.messages.append({"role": "assistant", "content": abort_msg})
                trace = self._finalize_trace(trace_id, t_start, step_traces, steps)
                yield {"type": "token", "delta": abort_msg}
                yield {"type": "done", "full_text": abort_msg, "model": self.model, "trace": trace.to_dict()}
                return

        fallback_msg = f"Agent reached the maximum tool execution limit ({self.max_steps} steps) without completing."
        self.messages.append({"role": "assistant", "content": fallback_msg})
        trace = self._finalize_trace(trace_id, t_start, step_traces, steps)
        yield {"type": "done", "full_text": fallback_msg, "model": self.model, "trace": trace.to_dict()}
