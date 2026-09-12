"""ReAct execution loop coordinating context, LLM inference, safety gates, and tool dispatch."""
import json
import logging
import re
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
        "calendar_get_free_slots",
    },
    "mail": {
        "mail_list_emails",
        "mail_fetch_unread",
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
    },
    "image_generation": {
        "generate_image",
    },
}

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "files_and_coding": [
        "file", "files", "folder", "folders", "code", "coding", "function", "class",
        "bug", "fix", "patch", "test", "tests", "pytest", "run", "terminal", "command",
        "repo", "git", "directory", "workspace", "syntax", "python", "javascript",
        "html", "css", "refactor", "lint", "inspect", "diff", "delete", "remove", "rm", "unlink", "trash",
        "graph", "symbol", "ast", "caller", "callee", "trace", "snippet", "architecture",
        ".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".yaml", ".yml", ".txt", ".sh", ".sql",
    ],
    "calendar": [
        "calendar", "event", "events", "meeting", "meetings", "schedule", "agenda",
        "free slot", "free slots", "free time", "busy", "appointment", "invite",
        "remind me on", "tomorrow", "yesterday", "wednesday", "thursday", "friday",
        "saturday", "sunday", "monday", "tuesday", "noon", "morning", "afternoon",
    ],
    "mail": [
        "mail", "email", "emails", "inbox", "unread", "draft", "drafts", "send email",
        "recipient", "sender", "subject", "reply", "compose", "gmail", "outlook",
    ],
    "notes": [
        "todo", "todos", "task", "tasks", "note", "notes", "daily note", "daily review",
        "checklist", "mark as completed", "completed task", "add task", "add todo",
    ],
    "web": [
        "search the web", "search online", "google", "lookup", "browse", "internet",
        "latest news", "weather", "who is", "what is the price", "url", "http", "https",
    ],
    "image_generation": [
        "generate image", "create image", "draw", "generate an image", "picture of",
        "make an image", "paint", "illustration", "sketch", "sdxl", "comfyui", "flux",
        "render an image", "photo of", "generate picture", "draw an image", "image of",
    ],
}


def detect_intent_domains(query: str) -> set[str]:
    """Detect capability domains relevant to a user query."""
    q_lower = f" {query.lower()} "
    detected: set[str] = set()

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
        self.client = client or OllamaClient(default_model=model)
        self.guard = guard or SafetyGuard()
        self.max_steps = max_steps
        self.custom_instructions = custom_instructions
        self.context_manager = context_manager or ContextManager()
        self.dynamic_tool_masking = dynamic_tool_masking

        self.tools_schema: list[dict[str, Any]] = []
        self.tool_dispatch: dict[str, Callable[..., Any]] = {}
        self.messages: list[dict[str, Any]] = []

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

    def _resolve_tool_name(self, name: str) -> str | None:
        """Fuzzily resolve tool names, accommodating missing underscores, case differences, and aliases common in 7B models."""
        if name in self.tool_dispatch:
            return name

        clean_target = name.lower().replace("_", "").replace("-", "").strip()

        # 1. Exact match ignoring underscores and case
        for registered in self.tool_dispatch:
            if registered.lower().replace("_", "").replace("-", "").strip() == clean_target:
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
        if clean_target in aliases and aliases[clean_target] in self.tool_dispatch:
            return aliases[clean_target]

        # 3. Check suffix match comparing normalized strings (e.g. model emitted "listtodos" or "list_directory")
        for registered in self.tool_dispatch:
            reg_clean = registered.lower().replace("_", "").replace("-", "").strip()
            if reg_clean.endswith(clean_target) or clean_target.endswith(reg_clean):
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

    def run_turn(self, user_input: str, images: list[str] | None = None) -> str:
        """Execute a full conversation turn with the user, handling multi-step tool calls and multimodal images."""
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

        steps = 0
        while steps < self.max_steps:
            steps += 1
            logger.debug("ReAct step %d for input: %s", steps, user_input[:50])

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
                        return f"Error during model inference: {retry_err}"
                else:
                    logger.error("Inference failed: %s", e)
                    return f"Error during model inference: {e}"

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

                # Normalize common parameter name variants across models
                if "path" not in args:
                    for k in ("file_path", "filename", "file", "filepath", "target_file", "path_to_file"):
                        if k in args:
                            args["path"] = args[k]
                            break
                if "content" not in args:
                    for k in ("text", "code", "data", "body"):
                        if k in args:
                            args["content"] = args[k]
                            break
                if "command" not in args and "cmd" in args:
                    args["command"] = args["cmd"]
                if "target" not in args and "old" in args:
                    args["target"] = args["old"]
                if "replacement" not in args and "new" in args:
                    args["replacement"] = args["new"]

                if fn_name not in self.tool_dispatch:
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
                        try:
                            res = func(**args)
                            tool_output = json.dumps(res) if isinstance(res, (dict, list)) else str(res)

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
                        except Exception as ex:
                            logger.error("Error executing tool %s: %s", fn_name, ex)
                            tool_output = json.dumps({
                                "status": "error",
                                "message": f"Execution error in '{fn_name}': {ex}",
                            })

                # Compress payload to prevent context window exhaustion (higher budget for code, directory, and command files)
                tool_budget = 12000 if fn_name in ("files_read_file", "files_search_files", "files_list_directory", "files_patch_file", "files_run_command", "files_set_workspace") else None
                safe_output = self.context_manager.compress_tool_result(str(tool_output), max_chars=tool_budget)

                # Append tool observation back to conversation history
                self.messages.append({
                    "role": "tool",
                    "name": fn_name,
                    "content": safe_output,
                })

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
        return fallback_msg

    def run_turn_stream(
        self,
        user_input: str,
        images: list[str] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Execute a full conversation turn yielding real-time stream events."""
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

        steps = 0
        while steps < self.max_steps:
            steps += 1
            logger.debug("ReAct stream step %d for input: %s", steps, user_input[:50])

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
                        if not accumulated_tool_calls:
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
                yield {"type": "error", "message": f"Error during model inference: {err_str}"}
                return

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
                yield {
                    "type": "done",
                    "full_text": final_content,
                    "model": self.model,
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

                if "path" not in args:
                    for k in ("file_path", "filename", "file", "filepath", "target_file", "path_to_file"):
                        if k in args:
                            args["path"] = args[k]
                            break
                if "content" not in args:
                    for k in ("text", "code", "data", "body"):
                        if k in args:
                            args["content"] = args[k]
                            break
                if "command" not in args and "cmd" in args:
                    args["command"] = args["cmd"]
                if "target" not in args and "old" in args:
                    args["target"] = args["old"]
                if "replacement" not in args and "new" in args:
                    args["replacement"] = args["new"]

                yield {"type": "tool_start", "tool": fn_name, "args": args}

                if fn_name not in self.tool_dispatch:
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
                        try:
                            res = func(**args)
                            tool_output = json.dumps(res) if isinstance(res, (dict, list)) else str(res)
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
                        except Exception as ex:
                            logger.error("Error executing tool %s: %s", fn_name, ex)
                            tool_output = json.dumps({
                                "status": "error",
                                "message": f"Execution error in '{fn_name}': {ex}",
                            })

                preview = str(tool_output)
                if len(preview) > 120:
                    preview = preview[:117] + "..."
                yield {"type": "tool_end", "tool": fn_name, "preview": preview}

                tool_budget = 12000 if fn_name in ("files_read_file", "files_search_files", "files_list_directory", "files_patch_file", "files_run_command", "files_set_workspace") else None
                safe_output = self.context_manager.compress_tool_result(str(tool_output), max_chars=tool_budget)

                self.messages.append({
                    "role": "tool",
                    "name": fn_name,
                    "content": safe_output,
                })

        fallback_msg = f"Agent reached the maximum tool execution limit ({self.max_steps} steps) without completing."
        self.messages.append({"role": "assistant", "content": fallback_msg})
        yield {"type": "done", "full_text": fallback_msg, "model": self.model}
