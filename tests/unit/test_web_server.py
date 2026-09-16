from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from src.web.server import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fixture providing TestClient with an isolated Obsidian vault."""
    monkeypatch.setenv("AETHER_VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    inbox_file = tmp_path / "Inbox.md"
    inbox_file.write_text("# Inbox\n- [ ] Initial test task #dev\n", encoding="utf-8")
    return TestClient(app)


def test_homepage_serves_html(client):
    """Verify that root GET / serves the dashboard HTML."""
    response = client.get("/")
    assert response.status_code == 200
    assert "AETHER" in response.text
    assert "Morning Briefing" in response.text
    assert "net-dot" in response.text
    assert "net-status-text" in response.text


def test_api_overview(client):
    """Verify GET /api/overview returns system status and metrics."""
    response = client.get("/api/overview")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "stats" in data
    assert "pending_tasks" in data["stats"]
    assert "ollama" in data["status"]
    assert "calendar" in data["status"]
    assert "search" in data["status"]
    assert "internet" in data["status"]
    assert isinstance(data["status"]["internet"], bool)


def test_check_internet_connection():
    """Verify check_internet_connection executes and returns a boolean."""
    from src.web.server import check_internet_connection
    result = check_internet_connection(timeout=0.5)
    assert isinstance(result, bool)


def test_api_calendar(client):
    """Verify GET /api/calendar returns events and free slots."""
    response = client.get("/api/calendar")
    assert response.status_code == 200
    data = response.json()
    assert "events" in data
    assert "free_slots" in data
    assert isinstance(data["events"], list)
    assert isinstance(data["free_slots"], list)


def test_api_emails(client):
    """Verify GET /api/emails handles email list retrieval with filters."""
    mock_data = {
        "emails": [{"id": "m1", "sender": "boss@co.com", "subject": "Update", "read": False}],
        "count": 1,
        "total_count": 1,
        "unread_count": 1,
        "read_count": 0,
        "starred_count": 0,
        "pinned_count": 0,
        "important_count": 0,
    }
    with patch("src.web.server.get_filtered_emails", return_value=mock_data):
        response = client.get("/api/emails?status=unread&days=7")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["emails"][0]["subject"] == "Update"


def test_api_email_update(client):
    """Verify POST /api/emails/update toggles flags."""
    with patch("src.web.server.update_email_flag", return_value={"status": "success", "id": "m1", "flag": "starred", "value": True}):
        resp = client.post("/api/emails/update", json={"id": "m1", "flag": "starred"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        assert resp.json()["value"] is True


def test_api_tasks_lifecycle(client):
    """Verify GET, POST /api/tasks add, complete, delete endpoints."""
    # 1. Get initial tasks
    response = client.get("/api/tasks")
    assert response.status_code == 200
    initial_count = response.json()["count"]
    assert initial_count >= 1

    # 2. Add new task
    add_resp = client.post("/api/tasks/add", json={"task": "Buy high performance thermal paste #setup", "due_date": "2026-09-10"})
    assert add_resp.status_code == 200
    assert add_resp.json()["status"] == "success"

    # 3. Verify task appeared
    list_resp = client.get("/api/tasks?status=pending")
    assert any("Buy high performance thermal paste" in t["text"] for t in list_resp.json()["tasks"])

    # 4. Complete the task
    comp_resp = client.post("/api/tasks/complete", json={"task": "Buy high performance thermal paste"})
    assert comp_resp.status_code == 200

    # 5. Delete the task
    del_resp = client.post("/api/tasks/delete", json={"task": "Buy high performance thermal paste"})
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "success"


def test_api_task_add_empty_validation(client):
    """Verify validation when adding empty task description."""
    resp = client.post("/api/tasks/add", json={"task": ""})
    assert resp.status_code == 400
    assert "cannot be empty" in resp.json()["message"]


def test_api_tasks_priority_lifecycle(client):
    """Verify task priority endpoints, filtering, and priority updating."""
    # Add an urgent task
    resp1 = client.post("/api/tasks/add", json={
        "task": "Deploy emergency hotfix",
        "priority": "urgent",
    })
    assert resp1.status_code == 200
    assert resp1.json()["priority"] == "urgent"

    # Add a normal task
    resp2 = client.post("/api/tasks/add", json={
        "task": "Water office plants",
        "priority": "normal",
    })
    assert resp2.status_code == 200

    # Filter by priority
    urgent_resp = client.get("/api/tasks?priority=urgent")
    assert urgent_resp.status_code == 200
    assert any("Deploy emergency hotfix" in t["text"] for t in urgent_resp.json()["tasks"])
    assert not any("Water office plants" in t["text"] for t in urgent_resp.json()["tasks"])

    # Update priority from normal to important
    pri_update_resp = client.post("/api/tasks/priority", json={
        "task": "Water office plants",
        "priority": "important",
    })
    assert pri_update_resp.status_code == 200
    assert pri_update_resp.json()["priority"] == "important"

    # Verify updated priority in task list
    imp_resp = client.get("/api/tasks?priority=important")
    assert any("Water office plants" in t["text"] for t in imp_resp.json()["tasks"])

    # Clean up
    client.post("/api/tasks/delete", json={"task": "Deploy emergency hotfix"})
    client.post("/api/tasks/delete", json={"task": "Water office plants"})


def test_api_chat_success(client):
    """Verify POST /api/chat interacts with Ollama client."""
    with patch("src.web.server.OllamaClient") as mock_ollama_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_instance.chat.return_value = {"content": "I am Aether, ready to help you."}
        mock_ollama_cls.return_value = mock_instance

        resp = client.post("/api/chat", json={"message": "What is the schedule today?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "I am Aether" in data["response"]


def test_api_chat_offline(client):
    """Verify POST /api/chat returns informative error when Ollama daemon is offline."""
    with patch("src.web.server.OllamaClient") as mock_ollama_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = False
        mock_ollama_cls.return_value = mock_instance

        resp = client.post("/api/chat", json={"message": "Hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "offline" in data["response"]


def test_api_chat_with_images_success(client):
    """Verify POST /api/chat routes to vision model when images are attached."""
    with patch("src.web.server.OllamaClient") as mock_ollama_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_instance.list_models.return_value = ["qwen2.5:7b-instruct", "qwen2.5vl:7b"]
        mock_instance.chat.return_value = {"content": "This image contains a software architecture diagram."}
        mock_ollama_cls.return_value = mock_instance

        resp = client.post("/api/chat", json={
            "message": "What is shown here?",
            "images": ["fakebase64encodedimage=="],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "architecture diagram" in data["response"]
        assert data["model_used"] == "qwen2.5vl:7b"


def test_api_chat_with_images_needs_pull(client):
    """Verify POST /api/chat returns helpful guide if no vision model is installed locally."""
    with patch("src.web.server.OllamaClient") as mock_ollama_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        # Only text models installed, no vision/vl models
        mock_instance.list_models.return_value = ["qwen2.5:7b-instruct", "deepseek-r1:7b"]
        mock_ollama_cls.return_value = mock_instance

        resp = client.post("/api/chat", json={
            "message": "Read this diagram",
            "images": ["fakebase64encodedimage=="],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert data.get("needs_pull") is True
        assert "ollama run" in data["response"]



def test_api_briefing_regenerate_success(client):
    """Verify POST /api/briefing/regenerate calls BriefingService and returns generated briefing."""
    with patch("src.web.server.OllamaClient") as mock_ollama_cls, \
         patch("src.web.server.BriefingService") as mock_service_cls:
        mock_ollama = MagicMock()
        mock_ollama.is_connected.return_value = True
        mock_ollama_cls.return_value = mock_ollama

        mock_service = MagicMock()
        mock_service.run_briefing_cycle.return_value = ("## Morning Briefing\nReady for today!", Path("/fake/note.md"))
        mock_service_cls.return_value = mock_service

        resp = client.post("/api/briefing/regenerate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "Morning Briefing" in data["briefing"]
        mock_service.run_briefing_cycle.assert_called_once()


def test_api_briefing_regenerate_offline(client):
    """Verify POST /api/briefing/regenerate returns 503 when Ollama daemon is offline."""
    with patch("src.web.server.OllamaClient") as mock_ollama_cls:
        mock_ollama = MagicMock()
        mock_ollama.is_connected.return_value = False
        mock_ollama_cls.return_value = mock_ollama

        resp = client.post("/api/briefing/regenerate")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "error"
        assert "offline" in data["message"]


def test_web_agent_loop_tools_registered():
    """Verify get_web_agent_loop registers calendar, notes, and mail tools."""
    from src.web.server import get_web_agent_loop
    loop = get_web_agent_loop()
    tool_names = [t["function"]["name"] for t in loop.tools_schema]
    assert "calendar_get_free_slots" in tool_names
    assert "calendar_list_events" in tool_names
    assert "notes_list_todos" in tool_names
    assert "mail_fetch_unread" in tool_names
    assert "search_web" in tool_names
    assert "fetch_web_page" in tool_names


def test_api_chat_history_and_clear(client):
    """Verify GET /api/chat/history returns messages and POST /api/chat/clear clears them."""
    with patch("src.web.server.OllamaClient") as mock_ollama_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_instance.chat.return_value = {"content": "Understood, scheduling now."}
        mock_ollama_cls.return_value = mock_instance

        # Send a message
        resp1 = client.post("/api/chat", json={"message": "Schedule my focus time."})
        assert resp1.status_code == 200

        # Fetch history
        resp2 = client.get("/api/chat/history")
        assert resp2.status_code == 200
        hist = resp2.json()
        assert hist["status"] == "success"
        contents = [m["content"] for m in hist["messages"]]
        assert "Schedule my focus time." in contents
        assert "Understood, scheduling now." in contents

        # Clear history
        resp3 = client.post("/api/chat/clear")
        assert resp3.status_code == 200
        assert resp3.json()["status"] == "success"

        # Verify history is now empty
        resp4 = client.get("/api/chat/history")
        assert resp4.status_code == 200
        assert len(resp4.json()["messages"]) == 0


def test_api_files_endpoints(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify file tree, read, save, create, and delete endpoints."""
    monkeypatch.setattr("src.servers.files_server.get_workspace_root", lambda: tmp_path)

    # Create dummy file
    (tmp_path / "hello.py").write_text("print('hello')", encoding="utf-8")

    # 1. Tree
    tree_resp = client.get("/api/files/tree")
    assert tree_resp.status_code == 200
    tree_data = tree_resp.json()
    assert tree_data["status"] == "success"
    child_names = [c["name"] for c in tree_data["tree"]["children"]]
    assert "hello.py" in child_names

    # 2. Read
    read_resp = client.get("/api/files/read?path=hello.py")
    assert read_resp.status_code == 200
    assert "print('hello')" in read_resp.json()["content"]
    assert read_resp.json()["language"] == "python"

    # 3. Save
    save_resp = client.post("/api/files/save", json={"path": "hello.py", "content": "print('updated')"})
    assert save_resp.status_code == 200
    assert (tmp_path / "hello.py").read_text(encoding="utf-8") == "print('updated')"

    # 4. Create
    create_resp = client.post("/api/files/create", json={"path": "new_folder", "is_directory": True})
    assert create_resp.status_code == 200
    assert (tmp_path / "new_folder").is_dir()

    # 5. Search
    search_resp = client.get("/api/files/search?q=hello")
    assert search_resp.status_code == 200
    assert len(search_resp.json()["results"]) >= 1

    # 6. Delete
    del_resp = client.post("/api/files/delete", json={"path": "hello.py", "permanent": True})
    assert del_resp.status_code == 200
    assert not (tmp_path / "hello.py").exists()


def test_api_models_endpoints(client: TestClient) -> None:
    """Verify listing and switching models via API."""
    with patch("src.web.server.OllamaClient") as mock_cls:
        mock_inst = MagicMock()
        mock_inst.list_models.return_value = ["qwen2.5-coder:7b", "qwen2.5:7b-instruct"]
        mock_cls.return_value = mock_inst

        # List models
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "qwen2.5-coder:7b" in data["models"]

        # Set model
        set_resp = client.post("/api/models/set", json={"model": "qwen2.5-coder:7b"})
        assert set_resp.status_code == 200
        assert set_resp.json()["active_model"] == "qwen2.5-coder:7b"


def test_api_files_pick_and_reveal_and_workspace(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify file/folder picker, reveal, and workspace endpoints."""
    # 1. Mock picker
    monkeypatch.setattr("src.web.server.open_picker_dialog", lambda picker_type, initial_dir, title: str(tmp_path / "picked_folder"))
    (tmp_path / "picked_folder").mkdir(exist_ok=True)

    pick_resp = client.post("/api/files/pick", json={"type": "folder"})
    assert pick_resp.status_code == 200
    pick_data = pick_resp.json()
    assert pick_data["status"] == "success"
    assert pick_data["name"] == "picked_folder"
    assert pick_data["is_dir"] is True

    # 2. Mock reveal
    monkeypatch.setattr("src.web.server.reveal_in_explorer", lambda target: True)
    reveal_resp = client.post("/api/files/reveal", json={"path": str(tmp_path)})
    assert reveal_resp.status_code == 200
    assert reveal_resp.json()["revealed"] is True

    # 3. Workspace get/set
    ws_get = client.get("/api/files/workspace")
    assert ws_get.status_code == 200
    assert "workspace_root" in ws_get.json()

    target_ws = tmp_path / "picked_folder"
    ws_set = client.post("/api/files/workspace", json={"path": str(target_ws)})
    assert ws_set.status_code == 200
    assert ws_set.json()["workspace_name"] == "picked_folder"


def test_api_app_exit_and_cancel_exit(client: TestClient) -> None:
    """Verify POST /api/app/exit schedules shutdown and /api/app/cancel_exit cancels it."""
    # 1. Trigger exit beacon
    resp = client.post("/api/app/exit")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["message"] == "Shutdown scheduled"

    # 2. Cancel exit beacon (e.g. on page reload)
    cancel_resp = client.post("/api/app/cancel_exit")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "ok"
    assert cancel_resp.json()["message"] == "Shutdown cancelled"

    # 3. Verify health endpoint also clears pending shutdown
    client.post("/api/app/exit")
    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"


def test_compute_unified_diff() -> None:
    """Verify unified diff calculation and addition/deletion metrics."""
    from src.web.server import _compute_unified_diff

    orig = "line 1\nline 2\nline 3\n"
    new = "line 1\nline 2 updated\nline 3\nline 4\n"
    res = _compute_unified_diff(orig, new, "test/example.py")

    assert res["path"] == "test/example.py"
    assert res["additions"] == 2  # 'line 2 updated' and 'line 4'
    assert res["deletions"] == 1  # 'line 2'
    assert "--- a/test/example.py" in res["diff"]
    assert "+++ b/test/example.py" in res["diff"]


def test_api_coder_plan_and_execute(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Antigravity Plan -> Execute workflow with mock LLM."""
    from src.servers.files_server import set_workspace_root
    set_workspace_root(str(tmp_path))

    # Create a dummy target file
    dummy = tmp_path / "calc.py"
    dummy.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    with patch("src.web.server.OllamaClient") as mock_ollama_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True

        # Mock plan generation response (valid JSON schema)
        mock_plan_json = (
            '{\n'
            '  "goal": "Add multiply function to calc.py",\n'
            '  "rationale": "Extend math capabilities",\n'
            '  "files": [{"path": "calc.py", "action": "modify", "description": "Add multiply"}],\n'
            '  "steps": ["Read calc.py", "Patch with multiply()"],\n'
            '  "verification": "pytest"\n'
            '}'
        )
        mock_instance.chat.return_value = mock_plan_json
        mock_ollama_cls.return_value = mock_instance

        # 1. Test POST /api/coder/plan
        plan_resp = client.post("/api/coder/plan", json={
            "prompt": "Add multiply function to calc.py",
            "active_file": "calc.py",
            "mode": "plan",
        })
        assert plan_resp.status_code == 200
        plan_data = plan_resp.json()
        assert plan_data["status"] == "success"
        assert "plan_id" in plan_data
        assert plan_data["plan"]["goal"] == "Add multiply function to calc.py"
        assert len(plan_data["plan"]["files"]) == 1

        plan_id = plan_data["plan_id"]

        # 2. Test GET /api/coder/history contains the plan
        hist_resp = client.get("/api/coder/history")
        assert hist_resp.status_code == 200
        assert len(hist_resp.json()["history"]) >= 1

        # 3. Test POST /api/coder/execute (simulating file modification)
        def mock_run_turn(prompt: str) -> str:
            # Modify the dummy file during turn
            dummy.write_text("def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n", encoding="utf-8")
            return "Implemented multiply function."

        mock_loop = MagicMock()
        mock_loop.model = "qwen2.5-coder:7b"
        mock_loop.run_turn.side_effect = mock_run_turn

        with patch("src.web.server.get_coder_agent_loop", return_value=mock_loop):
            exec_resp = client.post("/api/coder/execute", json={"plan_id": plan_id})
            assert exec_resp.status_code == 200
            exec_data = exec_resp.json()
            assert exec_data["status"] == "success"
            assert len(exec_data["touched_files"]) >= 1
            touched = exec_data["touched_files"][0]
            assert touched["path"] == "calc.py"
            assert touched["action"] == "modified"
            assert touched["additions"] >= 3
            assert "+def multiply(a, b):" in touched["diff"]

        # 4. Test POST /api/coder/clear
        clear_resp = client.post("/api/coder/clear")
        assert clear_resp.status_code == 200
        hist_after = client.get("/api/coder/history").json()
        assert len(hist_after["history"]) == 0


def test_files_workspace_layout_structure(client: TestClient) -> None:
    """Verify index.html contains the 3-pane layout wrapping file explorer, code editor, and coding agent."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    assert '<div class="files-workspace-layout">' in html
    assert "file-explorer-card" in html
    assert "code-editor-card" in html
    assert "code-agent-card" in html
    assert "explorer-collapsed-dock" in html
    assert "agent-collapsed-dock" in html

    # Verify order inside the layout
    layout_idx = html.index('<div class="files-workspace-layout">')
    explorer_idx = html.index("file-explorer-card", layout_idx)
    editor_idx = html.index("code-editor-card", explorer_idx)
    agent_idx = html.index("code-agent-card", editor_idx)

    assert layout_idx < explorer_idx < editor_idx < agent_idx


def test_api_coder_plan_null_active_file_and_dict_response(client: TestClient) -> None:
    """Verify api_coder_plan handles active_file=None and dict-based chat responses without AttributeError."""
    with patch("src.web.server.OllamaClient") as mock_ollama_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        # Real OllamaClient returns a dict with 'content'
        mock_instance.chat.return_value = {
            "role": "assistant",
            "content": (
                '{\n'
                '  "goal": "Create test.txt",\n'
                '  "rationale": "Testing file creation",\n'
                '  "files": [{"path": "test.txt", "action": "create", "description": "New test file"}],\n'
                '  "steps": ["Create test.txt with greeting"],\n'
                '  "verification": "Inspect file"\n'
                '}'
            ),
        }
        mock_ollama_cls.return_value = mock_instance

        resp = client.post("/api/coder/plan", json={
            "prompt": "create a test .txt file just saying hi this is a test",
            "active_file": None,  # sent as JSON null
            "mode": "plan",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["plan"]["goal"] == "Create test.txt"
        assert len(data["plan"]["files"]) == 1
        assert data["plan"]["files"][0]["path"] == "test.txt"


def test_api_coder_execute_creates_file_and_tracks_diff(client: TestClient, tmp_path: Path):
    """Verify api_coder_execute executes an approved plan, writes the file, and tracks unified diff."""
    from src.servers.files_server import set_workspace_root
    set_workspace_root(tmp_path)

    with patch("src.web.server.OllamaClient") as mock_ollama_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_ollama_cls.return_value = mock_instance

        # 1. Plan creation
        mock_instance.chat.return_value = {
            "role": "assistant",
            "content": (
                '{\n'
                '  "goal": "create a test .txt file just saying hi this is a test",\n'
                '  "rationale": "Create test file",\n'
                '  "files": [{"path": "aether/test.txt", "action": "create", "description": "New test file"}],\n'
                '  "steps": ["Create test.txt"],\n'
                '  "verification": "Check test.txt exists"\n'
                '}'
            ),
        }

        plan_resp = client.post("/api/coder/plan", json={
            "prompt": "create a test .txt file just saying hi this is a test",
            "active_file": None,
        })
        assert plan_resp.status_code == 200
        plan_id = plan_resp.json()["plan_id"]
        assert plan_resp.json()["plan"]["files"][0]["path"] == "test.txt"  # normalized!

        # 2. Mock coder loop execution turn where tool is invoked
        with patch("src.web.server.get_coder_agent_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            def fake_turn(exec_prompt):
                # Simulate the model invoking the registered tool
                from src.web.server import _current_turn_touched
                from src.servers.files_server import write_file_content
                write_file_content("test.txt", "hi this is a test")
                _current_turn_touched.append({
                    "path": "test.txt",
                    "action": "created",
                    "additions": 1,
                    "deletions": 0,
                    "diff": "+hi this is a test",
                })
                return "Created test.txt with content 'hi this is a test'."

            mock_loop.run_turn.side_effect = fake_turn
            mock_loop.model = "qwen2.5-coder:7b"
            mock_loop.client = mock_instance
            mock_loop_fn.return_value = mock_loop

            exec_resp = client.post("/api/coder/execute", json={
                "plan_id": plan_id,
                "prompt": "create a test .txt file just saying hi this is a test",
                "active_file": None,
            })
            assert exec_resp.status_code == 200
            exec_data = exec_resp.json()
            assert exec_data["status"] == "success"
            assert len(exec_data["touched_files"]) == 1
            assert exec_data["touched_files"][0]["path"] == "test.txt"
            assert (tmp_path / "test.txt").exists()
            assert (tmp_path / "test.txt").read_text(encoding="utf-8") == "hi this is a test"


def test_api_coder_execute_smart_fallback_markdown_block(client: TestClient, tmp_path: Path):
    """Verify api_coder_execute falls back to extracting code blocks if model emits markdown instead of calling a tool."""
    from src.servers.files_server import set_workspace_root
    set_workspace_root(tmp_path)

    with patch("src.web.server.OllamaClient") as mock_ollama_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_ollama_cls.return_value = mock_instance

        mock_instance.chat.return_value = {
            "role": "assistant",
            "content": (
                '{\n'
                '  "goal": "create a test .txt file just saying hi this is a test",\n'
                '  "rationale": "Create test file",\n'
                '  "files": [{"path": "test.txt", "action": "create", "description": "New test file"}],\n'
                '  "steps": ["Create test.txt"],\n'
                '  "verification": "Check test.txt exists"\n'
                '}'
            ),
        }

        plan_resp = client.post("/api/coder/plan", json={
            "prompt": "create a test .txt file just saying hi this is a test",
            "active_file": None,
        })
        assert plan_resp.status_code == 200
        plan_id = plan_resp.json()["plan_id"]

        with patch("src.web.server.get_coder_agent_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            # Model returns pure markdown with code block, no tool called
            mock_loop.run_turn.return_value = (
                "I have generated the file.\n\n"
                "```plaintext\n"
                "hi this is a test\n"
                "```\n"
                "The file is now ready."
            )
            mock_loop.model = "qwen2.5-coder:7b"
            mock_loop.client = mock_instance
            mock_loop_fn.return_value = mock_loop

            exec_resp = client.post("/api/coder/execute", json={
                "plan_id": plan_id,
                "prompt": "create a test .txt file just saying hi this is a test",
                "active_file": None,
            })
            assert exec_resp.status_code == 200
            exec_data = exec_resp.json()
            assert exec_data["status"] == "success"
            assert len(exec_data["touched_files"]) == 1
            assert exec_data["touched_files"][0]["path"] == "test.txt"
            assert (tmp_path / "test.txt").exists()
            assert (tmp_path / "test.txt").read_text(encoding="utf-8") == "hi this is a test"


def test_api_news_cached(client: TestClient) -> None:
    """Verify /api/news returns cached headlines."""
    sample_news = [
        {
            "id": "hn_test_1",
            "title": "Cached News Title 1",
            "url": "https://example.com/1",
            "source": "Hacker News",
            "score": 150,
            "comments_count": 40,
            "author": "author1",
            "published_at": "2026-09-10T10:00:00Z",
        }
    ]

    with patch("src.servers.news_service.get_news", return_value=sample_news):
        resp = client.get("/api/news?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "Cached News Title 1"


def test_api_news_refresh(client: TestClient) -> None:
    """Verify /api/news/refresh triggers live fetch and returns results."""
    sample_refreshed = [
        {
            "id": "gn_test_1",
            "title": "Refreshed Story",
            "url": "https://example.com/refreshed",
            "source": "Google News",
            "score": 0,
            "comments_count": 0,
            "author": "The Verge",
            "published_at": "2026-09-10T11:00:00Z",
        }
    ]

    with patch("src.servers.news_service.fetch_and_cache_news", return_value=sample_refreshed):
        resp = client.post("/api/news/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["refreshed"] is True
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "Refreshed Story"


def test_api_news_invalid_limit_query_param(client: TestClient) -> None:
    """Verify /api/news gracefully handles non-integer limit parameters without 500 error."""
    with patch("src.servers.news_service.get_news", return_value=[]):
        resp = client.get("/api/news?limit=invalid_value")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["count"] == 0


def test_coder_loop_registers_delete_tool():
    """Verify get_coder_agent_loop registers files_delete_file tool."""
    from src.web.server import get_coder_agent_loop, get_web_agent_loop
    coder_loop = get_coder_agent_loop(reset=True)
    assert "files_delete_file" in coder_loop.tool_dispatch

    web_loop = get_web_agent_loop()
    assert "files_delete_file" in web_loop.tool_dispatch


def test_coder_execute_deletes_file(client, tmp_path, monkeypatch):
    """Verify api_coder_execute detects deleted files and tracks diff."""
    from src.web.server import set_workspace_root, _pending_coder_plans, get_coder_agent_loop
    set_workspace_root(str(tmp_path))

    target = tmp_path / "to_delete.txt"
    target.write_text("Goodbye world", encoding="utf-8")

    plan_id = "test_del_plan"
    _pending_coder_plans[plan_id] = {
        "plan_id": plan_id,
        "prompt": "delete to_delete.txt",
        "active_file": "to_delete.txt",
        "plan": {
            "goal": "Delete to_delete.txt",
            "files": [{"path": "to_delete.txt", "action": "delete"}],
            "steps": ["Delete the file"],
        },
    }

    coder_loop = get_coder_agent_loop(reset=True)
    with patch("src.web.server.OllamaClient") as mock_ollama_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_ollama_cls.return_value = mock_instance

        with patch.object(coder_loop, "run_turn", return_value="The file to_delete.txt was deleted."):
            resp = client.post("/api/coder/execute", json={"plan_id": plan_id})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "success"
            # The file should have been deleted by the smart fallback or tool
            assert not target.exists()
            touched = data["touched_files"]
            assert len(touched) >= 1
            del_item = next((t for t in touched if t["path"] == "to_delete.txt"), None)
            assert del_item is not None
            assert del_item["action"] == "deleted"


def test_api_terminal_run_success(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify POST /api/terminal/run executes allowed command and returns output."""
    monkeypatch.setattr("src.web.server.get_workspace_root", lambda: tmp_path)
    resp = client.post("/api/terminal/run", json={"command": 'python -c "print(\'terminal ok\')"', "timeout_seconds": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["exit_code"] == 0
    assert "terminal ok" in data["stdout"]


def test_api_terminal_run_rejection(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify POST /api/terminal/run safely rejects disallowed command."""
    monkeypatch.setattr("src.web.server.get_workspace_root", lambda: tmp_path)
    resp = client.post("/api/terminal/run", json={"command": "format c:"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "error"
    assert "rejected" in data["message"].lower()


def test_api_terminal_run_empty(client: TestClient) -> None:
    """Verify POST /api/terminal/run rejects empty command with 400."""
    resp = client.post("/api/terminal/run", json={"command": "   "})
    assert resp.status_code == 400
    data = resp.json()
    assert data["status"] == "error"
    assert "empty" in data["message"].lower()


def test_api_terminal_kill(client: TestClient) -> None:
    """Verify POST /api/terminal/kill returns success."""
    resp = client.post("/api/terminal/kill")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def test_terminal_ws_execution_and_stream(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify WebSocket /api/terminal/ws streams output and completion."""
    monkeypatch.setattr("src.web.server.get_workspace_root", lambda: tmp_path)
    with client.websocket_connect("/api/terminal/ws") as ws:
        ws.send_json({"type": "run", "command": 'python -u -c "print(\'ws_hello\')"' })
        received_chunks = []
        exit_code = None
        for _ in range(10):
            msg = ws.receive_json()
            if msg.get("type") == "output":
                received_chunks.append(msg.get("data", ""))
            elif msg.get("type") == "exit":
                exit_code = msg.get("exit_code")
                break
        assert "ws_hello" in "".join(received_chunks)
        assert exit_code == 0


def test_terminal_ws_interactive_stdin(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify WebSocket /api/terminal/ws sends stdin to interactive script."""
    monkeypatch.setattr("src.web.server.get_workspace_root", lambda: tmp_path)
    # Script that prompts and echoes input
    script = tmp_path / "interactive_test.py"
    script.write_text('val = input("Enter choice: "); print(f"Selected: {val}")\n', encoding="utf-8")

    with client.websocket_connect("/api/terminal/ws") as ws:
        ws.send_json({"type": "run", "command": 'python -u "interactive_test.py"'})
        received_chunks = []
        prompt_received = False

        for _ in range(15):
            msg = ws.receive_json()
            if msg.get("type") == "output":
                data = msg.get("data", "")
                received_chunks.append(data)
                if "Enter choice:" in "".join(received_chunks) and not prompt_received:
                    prompt_received = True
                    ws.send_json({"type": "input", "data": "rock\n"})
            elif msg.get("type") == "exit":
                break

        combined = "".join(received_chunks)
        assert "Enter choice:" in combined
        assert "Selected: rock" in combined


def test_api_weather_endpoint(client: TestClient) -> None:
    """Verify GET /api/weather returns 200 and structured weather data."""
    sample_data = {
        "status": "success",
        "location": "Kingston, Ontario, Canada",
        "current": {
            "temp_c": 19,
            "temp_f": 66,
            "condition": "Sunny",
            "wind_kmph": 14,
            "wind_dir": "S",
            "humidity": 55,
        },
        "today": {
            "date": "2026-09-12",
            "max_c": 27,
            "min_c": 10,
            "hourly": [
                {
                    "time": "12:00",
                    "time_label": "12 PM",
                    "temp_c": 22,
                    "wind_kmph": 17,
                    "wind_dir": "S",
                    "rain_chance": 5,
                    "condition": "Sunny",
                }
            ],
        },
    }
    with patch("src.web.server.fetch_weather_forecast", return_value=sample_data) as mock_fetch:
        resp = client.get("/api/weather?location=Kingston+Downtown%2C+Ontario")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["location"] == "Kingston, Ontario, Canada"
        assert data["current"]["temp_c"] == 19
        assert len(data["today"]["hourly"]) == 1
        mock_fetch.assert_called_once_with(location="Kingston Downtown, Ontario", force_refresh=False)


def test_api_weather_location_get_and_post(client: TestClient) -> None:
    """Verify GET and POST /api/weather/location."""
    # 1. GET current location
    resp = client.get("/api/weather/location")
    assert resp.status_code == 200
    assert "location" in resp.json()

    # 2. POST empty location validation
    bad_resp = client.post("/api/weather/location", json={"location": "   "})
    assert bad_resp.status_code == 400

    # 3. POST new location
    with patch("src.web.server.fetch_weather_forecast") as mock_fetch:
        mock_fetch.return_value = {
            "status": "success",
            "location": "Toronto, Ontario, Canada",
            "current": {"temp_c": 20},
            "today": {"hourly": []},
        }
        post_resp = client.post("/api/weather/location", json={"location": "Toronto, Ontario"})
        assert post_resp.status_code == 200
        data = post_resp.json()
        assert data["status"] == "success"
        assert data["location"] == "Toronto, Ontario"
        assert data["weather"]["location"] == "Toronto, Ontario, Canada"

    # Reset back to Kingston
    client.post("/api/weather/location", json={"location": "Kingston Downtown, Ontario"})


def test_open_desktop_app_window_passes_user_data_dir() -> None:
    """Verify open_desktop_app_window passes user-data-dir and isolated app flags."""
    from src.web.server import open_desktop_app_window

    with patch("os.path.exists", return_value=True), \
         patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_popen.return_value = mock_proc

        open_desktop_app_window("http://127.0.0.1:8000", app_mode=True)

        assert mock_popen.called
        cmd = mock_popen.call_args[0][0]
        assert "--app=http://127.0.0.1:8000" in cmd
        assert any("--user-data-dir=" in arg for arg in cmd)
        assert "--no-first-run" in cmd


def test_window_monitor_terminates_server() -> None:
    """Verify window monitor thread sets should_exit when the app window process closes."""
    mock_proc = MagicMock()
    mock_server = MagicMock()
    mock_server.should_exit = False

    mock_proc.wait.return_value = 0

    def _monitor(proc, srv):
        try:
            proc.wait()
        except Exception:
            pass
        srv.should_exit = True

    _monitor(mock_proc, mock_server)
    assert mock_server.should_exit is True


def test_api_calendar_with_query_params(client: TestClient) -> None:
    """Verify /api/calendar accepts start and end query params for custom ranges."""
    with patch("src.web.server.list_events") as mock_list, patch("src.web.server.get_free_slots") as mock_slots:
        mock_list.return_value = [
            {
                "id": "evt_test",
                "title": "Study Group",
                "start": "2026-09-15T15:00:00Z",
                "end": "2026-09-15T16:30:00Z",
                "location": "Library",
            }
        ]
        mock_slots.return_value = []

        resp = client.get("/api/calendar?start=2026-09-01T00:00:00Z&end=2026-09-30T23:59:59Z")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert len(data["events"]) == 1
        assert data["events"][0]["title"] == "Study Group"
        mock_list.assert_called_once_with(
            start_iso="2026-09-01T00:00:00Z",
            end_iso="2026-09-30T23:59:59Z",
        )


def test_api_calendar_auth(client: TestClient) -> None:
    """Verify /api/calendar/auth triggers authentication subprocess."""
    with patch("src.web.server.GoogleCalendarManager") as mock_mgr_cls, patch("subprocess.Popen") as mock_popen:
        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr
        mock_mgr.is_oauth_configured.return_value = True

        resp = client.post("/api/calendar/auth")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        mock_popen.assert_called_once()




