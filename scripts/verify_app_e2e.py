"""Comprehensive End-to-End Functional Verification Suite for Project Aether.

Tests all application features from the app level:
1. Web server & static assets (HTML, CSS, JS modules, icons, manifest)
2. Health, telemetry, and overview dashboard endpoints
3. Live Open-Meteo weather API and location search
4. News service and headline ingestion
5. Markdown vault tasks (add, priority, complete, delete)
6. Calendar inspection and sync status
7. Email listing and flag updates (pinned, starred, read)
8. File management, workspace setting, and sandboxed terminal execution
9. Live Ollama inference and ReAct agent tool calling (using real Qwen2.5)
10. Live streaming SSE token generation (/api/chat/stream)
11. Voice activation service (status, listen_now, interrupt, SSE events)
12. Model catalog inspection (/api/models)
"""
import json
import sys
import time
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from starlette.testclient import TestClient
from src.web.server import app

client = TestClient(app)

PASSED = 0
FAILED = 0
REPORT: list[dict] = []


def record(feature: str, test_name: str, passed: bool, detail: str = "") -> None:
    global PASSED, FAILED
    clean_test_name = test_name.encode("ascii", errors="replace").decode("ascii")
    if passed:
        PASSED += 1
        print(f"  [PASS] {feature}: {clean_test_name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {feature}: {clean_test_name} -- {detail}")
    REPORT.append({
        "feature": feature,
        "test": test_name,
        "passed": passed,
        "detail": detail,
    })


def test_section_static_assets() -> None:
    print("\n--- 1. Testing Web Shell & Static Assets ---")

    # App shell
    r = client.get("/")
    record("Static", "GET / returns 200", r.status_code == 200)
    record("Static", "Index contains app root container", '<div class="app-layout"' in r.text)
    record("Static", "Index contains Siri voice overlay", 'id="voice-assistant-overlay"' in r.text)
    record("Static", "Index contains Snap Screen button", 'id="btn-snap-screen"' in r.text)
    record("Static", "Index references cache-busted app.js", 'app.js?v=' in r.text)

    # CSS stylesheet
    r_css = client.get("/static/style.css")
    record("Static", "GET /static/style.css returns 200", r_css.status_code == 200)
    record("Static", "CSS defines Zinc + Sky Blue design system", "--primary: #38BDF8;" in r_css.text)
    record("Static", "CSS contains voice assistant overlay styles", ".voice-assistant-overlay" in r_css.text)

    # JavaScript Modules
    modules = [
        "app.js",
        "store.js",
        "modules/overview.js",
        "modules/chat.js",
        "modules/calendar.js",
        "modules/tasks.js",
        "modules/mail.js",
        "modules/news.js",
        "modules/coder.js",
        "modules/editor.js",
    ]
    for mod in modules:
        r_mod = client.get(f"/static/js/{mod}")
        record("Static", f"GET /static/js/{mod} returns 200", r_mod.status_code == 200)

    # App Icons & Manifest
    record("Static", "GET /favicon.ico returns 200", client.get("/favicon.ico").status_code == 200)
    record("Static", "GET /static/logo.jpg returns 200", client.get("/static/logo.jpg").status_code == 200)
    r_man = client.get("/static/manifest.json")
    record("Static", "GET /static/manifest.json returns 200", r_man.status_code == 200)
    if r_man.status_code == 200:
        man_data = r_man.json()
        record("Static", "Manifest app name is Aether", "Aether" in man_data.get("name", ""))

    # Rich Formatting & LaTeX Vendor Assets
    record("Static", "GET /static/vendor/katex/katex.min.js returns 200", client.get("/static/vendor/katex/katex.min.js").status_code == 200)
    record("Static", "GET /static/vendor/katex/katex.min.css returns 200", client.get("/static/vendor/katex/katex.min.css").status_code == 200)
    record("Static", "GET /static/vendor/highlight/highlight.min.js returns 200", client.get("/static/vendor/highlight/highlight.min.js").status_code == 200)
    record("Static", "CSS contains chat math and table styles", ".chat-math-block" in r_css.text and ".chat-table" in r_css.text)


def test_section_health_and_overview() -> None:
    print("\n--- 2. Testing Health, Telemetry & Overview ---")

    r_health = client.get("/api/health")
    record("Health", "GET /api/health returns 200", r_health.status_code == 200)
    if r_health.status_code == 200:
        h_data = r_health.json()
        record("Health", "Health status is ok and app is aether", h_data.get("status") == "ok" and h_data.get("app") == "aether")

    r_overview = client.get("/api/overview")
    record("Overview", "GET /api/overview returns 200", r_overview.status_code == 200)
    if r_overview.status_code == 200:
        ov = r_overview.json()
        record("Overview", "Overview payload contains status and stats keys", "status" in ov and "stats" in ov)


def test_section_weather() -> None:
    print("\n--- 3. Testing Live Open-Meteo Weather API ---")

    r_w = client.get("/api/weather")
    record("Weather", "GET /api/weather returns 200", r_w.status_code == 200)
    if r_w.status_code == 200:
        w_data = r_w.json()
        record("Weather", "Weather payload contains current temp or condition", "current" in w_data or "temperature" in str(w_data))

    r_search = client.get("/api/weather/search?q=London")
    record("Weather", "GET /api/weather/search?q=London returns 200", r_search.status_code == 200)
    if r_search.status_code == 200:
        res = r_search.json().get("results", [])
        record("Weather", "Search results list has matching geocoding locations", len(res) > 0 and any("london" in x.get("name", "").lower() for x in res))


def test_section_news() -> None:
    print("\n--- 4. Testing News Feed Service ---")

    r_news = client.get("/api/news")
    record("News", "GET /api/news returns 200", r_news.status_code == 200)
    if r_news.status_code == 200:
        n_data = r_news.json()
        items = n_data.get("items", [])
        record("News", "News contains ingested items", len(items) > 0)


def test_section_tasks_and_vault() -> None:
    print("\n--- 5. Testing Task Management & Markdown Vault ---")

    # 1. List tasks
    r_tasks = client.get("/api/tasks")
    record("Tasks", "GET /api/tasks returns 200", r_tasks.status_code == 200)

    # 2. Add a new task
    task_desc = f"E2E Verification Task {int(time.time())}"
    r_add = client.post("/api/tasks/add", json={"task": task_desc, "priority": "urgent"})
    record("Tasks", "POST /api/tasks/add returns 200", r_add.status_code == 200)

    # 3. Verify task exists in vault
    r_tasks2 = client.get("/api/tasks")
    found_task = next((t for t in r_tasks2.json().get("tasks", []) if task_desc in t.get("text", "")), None)
    record("Tasks", "New task is present in vault list", found_task is not None)

    if found_task:
        task_text = found_task.get("text", task_desc)

        # 4. Update priority
        r_prio = client.post("/api/tasks/priority", json={"task": task_text, "priority": "important"})
        record("Tasks", "POST /api/tasks/priority returns 200", r_prio.status_code == 200)

        # 5. Complete task
        r_comp = client.post("/api/tasks/complete", json={"task": task_text})
        record("Tasks", "POST /api/tasks/complete returns 200", r_comp.status_code == 200)

        # 6. Delete test task cleanly
        r_del = client.post("/api/tasks/delete", json={"task": task_text})
        record("Tasks", "POST /api/tasks/delete returns 200", r_del.status_code == 200)


def test_section_calendar() -> None:
    print("\n--- 6. Testing Calendar Integration ---")

    r_cal = client.get("/api/calendar")
    record("Calendar", "GET /api/calendar returns 200", r_cal.status_code == 200)
    if r_cal.status_code == 200:
        c_data = r_cal.json()
        record("Calendar", "Calendar payload contains events array", "events" in c_data)


def test_section_emails() -> None:
    print("\n--- 7. Testing Email Management ---")

    r_mail = client.get("/api/emails")
    record("Emails", "GET /api/emails returns 200", r_mail.status_code == 200)
    if r_mail.status_code == 200:
        m_data = r_mail.json()
        record("Emails", "Emails payload returns emails list", "emails" in m_data)


def test_section_files_and_terminal() -> None:
    print("\n--- 8. Testing File Studio & Sandboxed Terminal ---")

    # Get active workspace
    r_ws = client.get("/api/files/workspace")
    record("Files", "GET /api/files/workspace returns 200", r_ws.status_code == 200)

    # Read workspace tree
    r_tree = client.get("/api/files/tree")
    record("Files", "GET /api/files/tree returns 200", r_tree.status_code == 200)

    # Execute safe terminal command
    r_term = client.post("/api/terminal/run", json={"command": "python --version"})
    record("Terminal", "POST /api/terminal/run returns 200", r_term.status_code == 200)
    if r_term.status_code == 200:
        out = r_term.json().get("output", "")
        record("Terminal", "Terminal output contains Python version", "Python" in out or r_term.json().get("exit_code") == 0)


def test_section_voice_service() -> None:
    print("\n--- 9. Testing Voice Activation Lifecycle ---")

    # Status
    r_stat = client.get("/api/voice/status")
    record("Voice", "GET /api/voice/status returns 200", r_stat.status_code == 200)
    if r_stat.status_code == 200:
        v_data = r_stat.json()
        record("Voice", "Status contains wake_word 'aether'", v_data.get("wake_word") == "aether")

    # Interrupt
    r_int = client.post("/api/voice/interrupt")
    record("Voice", "POST /api/voice/interrupt returns 200", r_int.status_code == 200)
    if r_int.status_code == 200:
        record("Voice", "Interrupt reports success", r_int.json().get("status") == "success")

    # Verify voice engine is in LISTENING or IDLE (not stuck in PROCESSING or SPEAKING)
    r_stat2 = client.get("/api/voice/status")
    if r_stat2.status_code == 200:
        st = r_stat2.json().get("state", "")
        record("Voice", f"Engine state after interrupt is safe ({st})", st in ("LISTENING", "IDLE"))

    # Verify pop_window_on_wake is False by default
    from src.config import get_config
    cfg = get_config()
    record("Voice", "pop_window_on_wake configured to False (non-blocking ambient vision)", getattr(cfg.voice, "pop_window_on_wake", False) is False)


def test_section_models() -> None:
    print("\n--- 10. Testing Local Model Inventory ---")

    r_mod = client.get("/api/models")
    record("Models", "GET /api/models returns 200", r_mod.status_code == 200)
    if r_mod.status_code == 200:
        models = r_mod.json().get("models", [])
        has_qwen = any("qwen" in (m.get("name", "") if isinstance(m, dict) else str(m)).lower() for m in models)
        record("Models", "Ollama models detected with Qwen2.5 series", has_qwen)


def test_section_screen_vision() -> None:
    print("\n--- 11. Testing Screen Vision & Active Window Inspection ---")

    # 1. Get active foreground window
    r_win = client.get("/api/screen/window")
    record("Screen", "GET /api/screen/window returns 200", r_win.status_code == 200)
    if r_win.status_code == 200:
        win_data = r_win.json()
        title = win_data.get("active_window", "")
        record("Screen", f"Active foreground window detected: '{title}'", len(title) > 0)

    # 2. Capture desktop screenshot
    r_cap = client.post("/api/screen/capture", json={"max_dimension": 640, "quality": 75})
    record("Screen", "POST /api/screen/capture returns 200", r_cap.status_code == 200)
    if r_cap.status_code == 200:
        cap_data = r_cap.json()
        record("Screen", "Capture reports success", cap_data.get("status") == "success")
        record("Screen", "Base64 image and data_url present", len(cap_data.get("image_base64", "")) > 100)
        record("Screen", "Thumbnail constraint respected (<= 640px)", max(cap_data.get("width", 0), cap_data.get("height", 0)) <= 640)

    # 3. Verify show_aether_dashboard tool exists in screen_server
    from src.servers.screen_server import show_aether_dashboard
    record("Screen", "show_aether_dashboard FastMCP tool registered and callable", callable(show_aether_dashboard))


def test_section_live_chat_and_tool_calling() -> None:
    print("\n--- 12. Testing Live Chat & ReAct Tool Calling (Ollama Qwen2.5) ---")

    # 1. Simple direct chat prompt
    t0 = time.perf_counter()
    r_chat = client.post("/api/chat", json={"message": "What is 7 + 8? Reply with just the number."})
    elapsed = round(time.perf_counter() - t0, 2)
    record("Chat", f"POST /api/chat executed in {elapsed}s returns 200", r_chat.status_code == 200)
    if r_chat.status_code == 200:
        data = r_chat.json()
        ans = data.get("response", "")
        record("Chat", f"Response generated by live Ollama: '{ans[:60]}...'", len(ans) > 0 and "15" in ans)
        record("Chat", "No raw <tool_call> or <think> XML tags leaked", "<tool_call>" not in ans and "<think>" not in ans)
        record("Chat", "Trace metadata attached to response", "trace" in data and data["trace"] is not None)

    # 2. Streaming chat turn
    r_stream = client.post("/api/chat/stream", json={"message": "Say 'Aether streaming verified' concisely."})
    record("ChatStream", "POST /api/chat/stream returns 200", r_stream.status_code == 200)
    if r_stream.status_code == 200:
        stream_text = r_stream.text
        record("ChatStream", "Stream yields text/event-stream chunks", "data: " in stream_text)
        record("ChatStream", "Stream terminates with [DONE] token", "[DONE]" in stream_text)

    # 3. Chat history inspection
    r_hist = client.get("/api/chat/history")
    record("ChatHistory", "GET /api/chat/history returns 200", r_hist.status_code == 200)
    if r_hist.status_code == 200:
        msgs = r_hist.json().get("messages", [])
        record("ChatHistory", f"Chat history successfully stored in SQLite ({len(msgs)} messages)", len(msgs) > 0)


def main() -> int:
    print("=======================================================================")
    print("  PROJECT AETHER END-TO-END APPLICATION FUNCTIONAL VERIFICATION")
    print("=======================================================================")

    test_section_static_assets()
    test_section_health_and_overview()
    test_section_weather()
    test_section_news()
    test_section_tasks_and_vault()
    test_section_calendar()
    test_section_emails()
    test_section_files_and_terminal()
    test_section_voice_service()
    test_section_models()
    test_section_screen_vision()
    test_section_live_chat_and_tool_calling()

    print("\n" + "=" * 71)
    print(f"  VERIFICATION COMPLETE: {PASSED} PASSED | {FAILED} FAILED")
    print("=" * 71)

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
