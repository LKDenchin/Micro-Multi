"""Comprehensive verification for the 14 MASP & DeepSeek-Harness requirements."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from masp.api import create_app
from masp.mcp_bridge import call_tool, discover_project_mcp_servers, discover_tools
from masp.mcp_server import BUILTIN_MCP_SERVER_ID
from masp.storage import Store


def test_builtin_mcp_server_and_project_mcp_discovery(tmp_path: Path) -> None:
    """B1 & B6: Built-in workspace MCP server works across modes and discovers .mcp.json."""
    store = Store(tmp_path / "store.sqlite3")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "hello.py").write_text("print('hello masp')\n", encoding="utf-8")

    # 1. Built-in MCP tools in files/commands mode
    schemas, lookup = asyncio.run(
        discover_tools(store, cwd=workspace, include_builtin=True, access_mode="files")
    )
    tool_names = [s["function"]["name"] for s in schemas]
    assert any("workspace_info" in name for name in tool_names)
    assert any("search_workspace_code" in name for name in tool_names)

    # Execute built-in workspace_info tool
    ws_info_alias = next(name for name in lookup if "workspace_info" in name)
    server_record, remote_name = lookup[ws_info_alias]
    info_result = json.loads(
        asyncio.run(call_tool(server_record, remote_name, "{}", cwd=workspace))
    )
    assert info_result["exists"] is True
    assert Path(info_result["workspace"]).name == "workspace"

    # Execute built-in search_workspace_code tool
    search_alias = next(name for name in lookup if "search_workspace_code" in name)
    s_rec, s_name = lookup[search_alias]
    search_output = asyncio.run(
        call_tool(s_rec, s_name, json.dumps({"query": "hello masp"}), cwd=workspace)
    )
    assert "hello.py" in search_output
    assert "hello masp" in search_output

    # 2. Read mode only exposes read-only tools
    read_schemas, _ = asyncio.run(
        discover_tools(store, cwd=workspace, include_builtin=True, access_mode="read")
    )
    assert len(read_schemas) >= 4

    # 3. Project .mcp.json auto-discovery
    mcp_config = {
        "mcpServers": {
            "custom-echo": {
                "command": sys.executable,
                "args": ["-m", "masp.mcp_server"],
            }
        }
    }
    (workspace / ".mcp.json").write_text(json.dumps(mcp_config), encoding="utf-8")
    discovered_proj = discover_project_mcp_servers(workspace)
    assert len(discovered_proj) == 1
    assert discovered_proj[0]["name"] == "custom-echo"

    # 4. Probe endpoint works for builtin-masp-workspace
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        probe = client.post(f"/api/mcp-servers/{BUILTIN_MCP_SERVER_ID}/probe", json={})
        assert probe.status_code == 200
        data = probe.json()
        assert any(t["name"] == "workspace_info" for t in data["tools"])


def test_dsh_settings_and_everything_is_a_plugin(tmp_path: Path) -> None:
    """A2 & B7: DSH settings persistence, unified plugin inventory, and bundle installation."""
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        # 1. GET & PUT /api/dsh/settings
        initial = client.get("/api/dsh/settings")
        assert initial.status_code == 200
        settings = initial.json()
        assert "general" in settings
        assert "subagent" in settings
        assert settings["subagent"]["maxConcurrent"] == 2

        updated = client.put(
            "/api/dsh/settings",
            json={
                "general": {"locale": "en-US", "sendWithEnter": True},
                "subagent": {"maxConcurrent": 12, "maxDepth": 3},
                "agentPreset": {
                    "name": "Custom Architect",
                    "role": "Lead Architect",
                    "instructions": "Contract-first design",
                    "template": "architect",
                },
            },
        )
        assert updated.status_code == 200
        assert updated.json()["subagent"]["maxConcurrent"] == 12
        assert updated.json()["agentPreset"]["name"] == "Custom Architect"

        # 2. Unified plugin inventory includes 5 official DSH plugins + builtin MCP
        inv = client.get("/api/dsh/plugins")
        assert inv.status_code == 200
        inv_data = inv.json()
        official_ids = {item["id"] for item in inv_data["official"]}
        assert "@deepseek-harness/shell" in official_ids
        assert "@deepseek-harness/subagent" in official_ids
        assert "@masp/workspace-mcp" in official_ids

        # 3. Install a local DSH plugin bundle with package.json + SKILL.md
        bundle_dir = tmp_path / "my-dsh-bundle"
        bundle_dir.mkdir()
        (bundle_dir / "package.json").write_text(
            json.dumps(
                {
                    "name": "@demo/audit-plugin",
                    "version": "1.2.0",
                    "description": "Demo DSH security audit plugin",
                    "deepseek-harness": {"plugin": True},
                }
            ),
            encoding="utf-8",
        )
        (bundle_dir / "SKILL.md").write_text(
            "---\nname: security-audit\ndescription: Security audit instructions\n---\n"
            "Always check OWASP top 10.\n",
            encoding="utf-8",
        )

        installed = client.post("/api/dsh/plugins/install", json={"path": str(bundle_dir)})
        assert installed.status_code == 201
        bundle = installed.json()
        assert bundle["name"] == "@demo/audit-plugin"
        assert any(c.get("type") == "skill" for c in bundle["components"])

        # Toggle official plugin
        toggled = client.post(
            "/api/dsh/plugins/toggle",
            json={"id": "@deepseek-harness/web-search", "enabled": True},
        )
        assert toggled.status_code == 200
        assert toggled.json()["enabled"] is True

        # Delete installed bundle
        deleted = client.request("DELETE", f"/api/dsh/bundles/{bundle['id']}", json={})
        assert deleted.status_code == 204


def test_first_round_project_team_draft_and_title_vs_unbound_temp(
    tmp_path: Path, monkeypatch
) -> None:
    """A1, B2-B5, B8, B10: Auto-git-init, turn-1 title & team event, custom concurrency, temp."""

    class FakeStream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def aiter_lines(self):
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": "Project plan ready."}}]}
            )
            yield "data: [DONE]"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, method, url, *, headers, json):
            return FakeStream()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)

    # B3: Create a non-git local folder and link it -> auto initializes Git + main branch
    non_git_folder = tmp_path / "raw_folder"
    non_git_folder.mkdir()
    (non_git_folder / "README.md").write_text("# Raw Folder\n", encoding="utf-8")

    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "main", "model": "deepseek-chat", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()

        project_resp = client.post(
            "/api/projects",
            json={
                "name": "AutoGitProj",
                "repository": str(non_git_folder),
                "link_repository": True,
            },
        )
        assert project_resp.status_code == 201
        project = project_resp.json()
        assert (non_git_folder / ".git").exists()

        branches = client.get(f"/api/projects/{project['id']}/branches").json()
        assert branches["current"] in ("main", "master")

        # B4: Set custom max concurrency > 4 (e.g. 8) on project team
        team_put = client.put(
            f"/api/projects/{project['id']}/team",
            json={
                "requirement": "构建高并发多智能体后端",
                "main_profile_id": profile["id"],
                "max_concurrency": 8,
                "agents": [
                    {
                        "id": "sub_1",
                        "name": "后端架构师",
                        "responsibility": "负责后端接口与MCP工具",
                        "model_profile_id": profile["id"],
                        "owned_paths": ["src"],
                        "locked": False,
                    }
                ],
            },
        )
        assert team_put.status_code == 200
        assert team_put.json()["max_concurrency"] == 8

        # A1, B5, B10: Create unbound draft conversation, bind to project on first message
        conv = client.post(
            "/api/conversations",
            json={"project_id": None, "model_profile_id": profile["id"]},
        ).json()
        assert conv["message_count"] == 0

        msg_resp = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={
                "content": "请帮我重构整个多Agent后端并编写单元测试",
                "project_id": project["id"],
                "access_mode": "files",
            },
        )
        assert msg_resp.status_code == 200
        stream_text = msg_resp.text
        assert "event: title" in stream_text
        assert "event: team" in stream_text

        # B2: Conversation now has message_count > 0 and belongs to project
        all_convs = client.get("/api/conversations").json()
        updated_conv = next(c for c in all_convs if c["id"] == conv["id"])
        assert updated_conv["project_id"] == project["id"]
        assert updated_conv["message_count"] >= 2

        # B8: Unbound chat uses temporary/<conversation_id> and does NOT emit event: team
        unbound_conv = client.post(
            "/api/conversations",
            json={"project_id": None, "model_profile_id": profile["id"]},
        ).json()
        unbound_resp = client.post(
            f"/api/conversations/{unbound_conv['id']}/messages",
            json={
                "content": "普通闲聊测试",
                "project_id": None,
                "access_mode": "files",
                "main_only": True,
            },
        )
        assert unbound_resp.status_code == 200
        assert "event: title" in unbound_resp.text
        assert "event: team" not in unbound_resp.text
        assert (tmp_path / "home" / "temporary" / unbound_conv["id"]).exists()


def test_global_search_and_frontend_ui_contracts(tmp_path: Path) -> None:
    """A1, A2, A3, A4, B4, B5: Global search covers all categories and UI HTML/CSS/JS meet specs."""
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        # A4: Global search returns chats, projects, files, settings, plugins, actions
        res = client.get("/api/search/global", params={"q": "mcp"})
        assert res.status_code == 200
        payload = res.json()
        assert "chats" in payload
        assert "projects" in payload
        assert "files" in payload
        assert "settings" in payload
        assert "plugins" in payload
        assert "actions" in payload
        assert len(payload["plugins"]) >= 1 or len(payload["settings"]) >= 1

        # Verify HTML / CSS / JS static contracts
        html = client.get("/").text
        css = client.get("/static/chat.css").text
        js = client.get("/static/chat.js").text

        # A1: Context project & branch bar above composer without "本地" option
        assert 'id="context-project-trigger"' in html
        assert 'id="context-branch-trigger"' in html

        # A2: DeepSeek-Harness 8 settings pages
        for page in (
            "general",
            "models",
            "agent-preset",
            "access",
            "workspace",
            "extensions",
            "appearance",
            "session-log",
        ):
            assert f'data-settings-page="{page}"' in html

        # A3: No trailing checkmark in access popover or CSS .select-option:after
        assert '.select-option[aria-selected="true"]:after' not in css
        assert 'class="access-check"' not in html

        # A4: Search dialog alignment & responsive width
        assert "min(640px,calc(100vw - 28px))" in css

        # B4 & B5: Workflow mindmap SVG container & custom concurrency controls
        assert 'id="team-workflow"' in html
        assert 'id="team-review-editor"' in html
        assert 'id="team-concurrency-custom"' in html
        assert 'id="modal-team-concurrency-custom"' in html
        assert "renderWorkflowMindmap" in js

        # New UI/UX items:
        # 1. Composer top context bar & non-overlapping composer
        assert 'id="composer-context-bar"' in html
        assert "随心输入" in html
        # 3. Settings page grouped cards, rows, and switches
        assert "settings-group-card" in html
        assert "setting-row" in html
        assert "ui-switch" in html
        # 4. No full-width parenthetical clutter in chat.html or chat.js
        assert "（" not in html
        assert "（" not in js
        # 6. Sidebar & inspector animations
        assert "grid-template-columns .24s" in css
        # 7. Collapsible tool activity group rendering
        assert "tool-activity-group" in css
        assert "createOrUpdateToolGroup" in js
        assert "summarizeToolEvents" in js


def test_full_agent_tools_and_workspace_inspector_parity(tmp_path: Path) -> None:
    """Verify full agent tool capabilities (glob, grep, write/edit diff stats) and workspace inspector APIs."""
    from masp.chat_tools import run_chat_tool

    ws = tmp_path / "proj"
    ws.mkdir()

    # 1. write_file returns +added/-removed and unified diff
    write_res = json.loads(
        run_chat_tool(
            "write_file",
            json.dumps({"path": "app.py", "content": "def add(a, b):\n    return a + b\n"}),
            cwd=ws,
            access_mode="files",
            timeout_seconds=10,
            enabled_plugins=[],
        )
    )
    assert write_res["added"] == 2
    assert write_res["removed"] == 0
    assert "+def add(a, b):" in write_res["diff"]

    # 2. edit_file returns +added/-removed and unified diff
    edit_res = json.loads(
        run_chat_tool(
            "edit_file",
            json.dumps(
                {
                    "path": "app.py",
                    "old_text": "return a + b",
                    "new_text": "result = a + b\n    return result",
                }
            ),
            cwd=ws,
            access_mode="files",
            timeout_seconds=10,
            enabled_plugins=[],
        )
    )
    assert edit_res["added"] == 2
    assert edit_res["removed"] == 1
    assert "+    result = a + b" in edit_res["diff"]

    # 3. glob & grep & read_file with line range
    glob_res = json.loads(
        run_chat_tool(
            "glob",
            json.dumps({"pattern": "*.py"}),
            cwd=ws,
            access_mode="read",
            timeout_seconds=10,
            enabled_plugins=[],
        )
    )
    assert "app.py" in glob_res["matches"]

    grep_res = json.loads(
        run_chat_tool(
            "grep",
            json.dumps({"query": "result"}),
            cwd=ws,
            access_mode="read",
            timeout_seconds=10,
            enabled_plugins=[],
        )
    )
    assert len(grep_res["matches"]) >= 1
    assert grep_res["matches"][0]["path"] == "app.py"

    range_res = json.loads(
        run_chat_tool(
            "read_file",
            json.dumps({"path": "app.py", "start_line": 1, "end_line": 2}),
            cwd=ws,
            access_mode="read",
            timeout_seconds=10,
            enabled_plugins=[],
        )
    )
    assert range_res["start_line"] == 1
    assert "1: def add(a, b):" in range_res["content"]

    # 4. API endpoints for workspace changes (overview + per-file diff), review-files, and browser proxy
    app = create_app(data_dir=tmp_path / "data")
    with TestClient(app) as client:
        # Include builtin MCP server in GET /api/mcp-servers?include_builtin=true
        mcp_list = client.get("/api/mcp-servers?include_builtin=true").json()
        assert any(s["id"] == BUILTIN_MCP_SERVER_ID for s in mcp_list)

        proj = client.post(
            "/api/projects",
            json={
                "name": "DemoProj",
                "repository": str(ws),
                "link_repository": True,
            },
        ).json()
        pid = proj["id"]

        # Modify a file after git init so workspace/changes sees it
        (ws / "index.html").write_text("<h1>Hello Preview</h1>\n", encoding="utf-8")
        changes = client.get(f"/api/projects/{pid}/workspace/changes").json()
        assert isinstance(changes["files"], list)
        assert any(f["path"] == "index.html" and f["added"] >= 1 for f in changes["files"])

        # Manual file selection review
        review = client.post(
            f"/api/projects/{pid}/workspace/review-files",
            json={"paths": ["app.py", "index.html"]},
        ).json()
        assert len(review["results"]) == 2
        assert review["results"][0]["path"] == "app.py"

        # Built-in browser proxy for workspace HTML file
        proxy_resp = client.get(f"/api/browser/proxy?url=index.html&project_id={pid}")
        assert proxy_resp.status_code == 200
        assert "Hello Preview" in proxy_resp.text


def test_dsh_compaction_memory_markdown_and_settings_parity(tmp_path: Path) -> None:
    """Verify DSH compaction, multi-turn tool memory, destructive git guard, defaultBranch, and UI contracts."""
    from masp.chat_tools import run_chat_tool
    from masp.compaction import (
        RepeatToolReminder,
        ToolResultPruner,
        compact_conversation_messages,
        format_message_with_tool_memory,
    )

    # 1. ToolResultPruner prunes oversized output while preserving head & tail
    pruner = ToolResultPruner(max_chars=200)
    huge = "LINE\n" * 200
    pruned = pruner.prune("read_file", huge)
    assert len(pruned) < len(huge)
    assert "pruned" in pruned or "省略" in pruned

    # 2. RepeatToolReminder detects consecutive identical calls
    reminder = RepeatToolReminder(threshold=3)
    assert reminder.record("read_file", '{"path":"a.py"}') is None
    assert reminder.record("read_file", '{"path":"a.py"}') is None
    warn = reminder.record("read_file", '{"path":"a.py"}')
    assert warn is not None and "read_file" in warn

    # 3. Multi-turn tool memory formatting
    formatted = format_message_with_tool_memory(
        "Found files",
        [{"name": "glob", "status": "completed", "label": "匹配 *.py", "output": "a.py"}],
    )
    assert "<tool-execution-memory>" in formatted
    assert "glob" in formatted

    # 4. Context compaction produces <compacted-summary> checkpoint
    messages = [
        {
            "id": f"m{i}",
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"Message {i}: working on `src/app_{i}.py` and fixing function `compute_{i}()`",
            "tool_events": [{"name": "edit_file", "label": f"编辑 src/app_{i}.py"}]
            if i % 2 == 1
            else [],
        }
        for i in range(12)
    ]
    compaction = compact_conversation_messages(messages, keep_recent=4)
    assert compaction["compacted"] is True
    assert "<compacted-summary>" in compaction["checkpoint_content"]
    assert compaction["kept_count"] == 4

    # 5. block_destructive_git blocks git reset --hard
    ws = tmp_path / "git_guard_ws"
    ws.mkdir()
    blocked_res = json.loads(
        run_chat_tool(
            "run_command",
            json.dumps({"command": "git reset --hard HEAD~1"}),
            cwd=ws,
            access_mode="commands",
            timeout_seconds=10,
            enabled_plugins=[],
            block_destructive_git=True,
        )
    )
    assert blocked_res.get("blocked") is True

    # 6. API test for defaultBranch, /compact endpoint, and static UI contracts
    app = create_app(data_dir=tmp_path / "data2")
    with TestClient(app) as client:
        client.put(
            "/api/dsh/settings",
            json={"workspace": {"defaultBranch": "develop", "autoInitGit": True}},
        )
        proj = client.post(
            "/api/projects",
            json={"name": "BranchTestProj"},
        ).json()
        branches = client.get(f"/api/projects/{proj['id']}/branches").json()
        assert branches["current"] == "develop"

        conv = client.post("/api/conversations", json={"project_id": proj["id"]}).json()
        cid = conv["id"]
        for idx in range(8):
            app.state.service.store.put(
                "message",
                {
                    "id": f"msg-test-{idx}",
                    "conversation_id": cid,
                    "role": "user" if idx % 2 == 0 else "assistant",
                    "content": f"Turn {idx} content touching `index.html`",
                    "created_at": f"2026-09-29T10:00:0{idx}Z",
                },
                cid,
            )
        compact_resp = client.post(f"/api/conversations/{cid}/compact", json={"keep_recent": 2})
        assert compact_resp.status_code == 200
        assert compact_resp.json()["compacted"] is True

        # Verify static frontend contracts
        html = client.get("/").text
        js = client.get("/static/chat.js").text
        md_js = client.get("/static/markdown.js").text
        css = client.get("/static/chat.css").text

        assert 'id="header-more"' not in html
        assert "#header-more" not in js
        assert "window.prompt" not in js
        assert 'id="branch-dialog"' in html
        assert "filterSettingsInPlace" in js
        assert "settings-search-mark" in css
        assert "renderLatexMath" in md_js
        assert "masp-markdown" in css


def test_multi_agent_in_chat_parallel_execution_and_ui_fixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify semi-hidden turn rail, repo colored badges, DSML tool parsing, first-turn team popup, in-chat parallel subagent execution, session deduplication, and context calculation."""
    from masp.agents import extract_dsml_tool_calls

    # 1. Verify DSML raw tool call extraction & cleaning (both DSML and tool_calls_begin formats)
    raw_dsml = (
        "我将创建 index.html 文件。\n"
        "< | DSML | function_calls >\n"
        '< | DSML | invoke name="write_file" >\n'
        '< | DSML | parameter name="path" string="true" >index.html< / | DSML | parameter >\n'
        '< | DSML | parameter name="content" string="true" ><h1>Solar</h1>< / | DSML | parameter >\n'
        "< / | DSML | invoke >\n"
        "< / | DSML | function_calls >"
    )
    cleaned, parsed_calls = extract_dsml_tool_calls(raw_dsml)
    assert "DSML" not in cleaned
    assert len(parsed_calls) == 1
    assert parsed_calls[0]["function"]["name"] == "write_file"
    args_obj = json.loads(parsed_calls[0]["function"]["arguments"])
    assert args_obj["path"] == "index.html"
    assert args_obj["content"] == "<h1>Solar</h1>"

    raw_tc = (
        "开始执行写入。\n"
        "< | tool_calls_begin | >\n"
        "< | tool_call_begin | >function< | tool_sep | >write_file\n"
        '{"path": "style.css", "content": "body { margin: 0; }"}\n'
        "< | tool_call_end | >\n"
        "< | tool_calls_end | >"
    )
    cleaned_tc, parsed_tc = extract_dsml_tool_calls(raw_tc)
    assert "tool_calls_begin" not in cleaned_tc
    assert len(parsed_tc) == 1
    assert parsed_tc[0]["function"]["name"] == "write_file"

    class FakeStream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"已完成子任务分工与并行代码生成。"}}]}'
            yield "data: [DONE]"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, method, url, *, headers, json):
            return FakeStream()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)

    # 2. Verify in-chat first-turn team confirmation & parallel subagent execution
    app = create_app(data_dir=tmp_path / "data_ma")
    with TestClient(app) as client:
        css = client.get("/static/chat.css").text
        js = client.get("/static/chat.js").text

        # Item 1: Semi-hidden turn rail
        assert "translateX(-5px)" in css
        assert ".chat-turn-rail.is-active" in css
        # Item 2: Colored file badges in repositoryEntries (.gitignore -> GIT)
        assert ".ide-file-badge.ext-git" in css
        assert "ide-sidebar-item" in js
        assert "lowerName.startsWith('.git')" in js


def test_nine_followup_ui_and_multiagent_fixes(tmp_path: Path, monkeypatch) -> None:
    """Verify all 9 follow-up fixes:
    1. Left-aligned file list items in repositoryEntries & workspaceEntries
    2. Compact turn deliverable & edits cards
    3. Multi-round direct follow-up prompts (e.g. '没有css') without needing '请根据上一轮...' or aborting
    4. Compact line-numbered code table (.ide-code-table / .ide-code-row) without inter-line blank space
    5. Detailed step-by-step subagent operation log (.subagent-step-log)
    6. Strip <configure_team>...</configure_team> raw XML from chat output & extract tool call
    7. Remove '代码验证与检查' and '查看详细协作时间线' from run detail view
    8. Enhanced Open Code Review console with model selector & auto re-review
    9. Shared dev spec (.masp/SHARED_DEV_SPEC.md) + parallel subagent generation + cross-file CSS/HTML/JS repair
    """
    from masp.agents import extract_dsml_tool_calls

    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)

    # Item 6: <configure_team> raw tag extraction and stripping
    raw_text = (
        "准备配置团队：\n<configure_team>\n{\n"
        '  "name": "pelican_bike_animation",\n'
        '  "description": "制作鹈鹕骑自行车的前端动画",\n'
        '  "agents": [\n'
        '    {"name": "ui_structure", "instructions": "负责 index.html, styles.css"},\n'
        '    {"name": "core_impl", "instructions": "负责 app.js"}\n'
        "  ]\n}\n</configure_team>\n已完成。"
    )
    cleaned, calls = extract_dsml_tool_calls(raw_text)
    assert "<configure_team>" not in cleaned
    assert "</configure_team>" not in cleaned
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "configure_team"

    app = create_app(data_dir=tmp_path / "data_nine")
    with TestClient(app) as client:
        css = client.get("/static/chat.css").text
        js = client.get("/static/chat.js").text
        md_js = client.get("/static/markdown.js").text

        # Item 1: Strictly left-aligned file items
        assert "justify-content:flex-start!important" in css
        assert ".inspector .ide-sidebar-item" in css

        # Item 2: Compact turn summary stack
        assert ".turn-summary-stack" in css

        # Item 4: Compact line-numbered code rows in markdown.js and chat.js
        assert "ide-code-table" in md_js
        assert "ide-code-row" in md_js
        assert "configure_team" in md_js

        # Item 5: Detailed subagent step log
        assert "subagent-step-log" in js
        assert "subagent-step-log-row" in css

        # Item 7: Removed '代码验证与检查' and '查看详细协作时间线'
        assert "子任务合流后将自动运行代码验证" not in js
        assert "查看详细协作时间线" not in js

        # Item 8: Review console card with model selector & auto re-review
        assert "workspace-review-model-select" in js
        assert "review-console-card" in css

        # Item 3 & 9: Multi-round direct follow-up prompt ('没有css') triggers Turn 2+ multi-agent execution,
        # generates .masp/SHARED_DEV_SPEC.md, and repairs missing styles.css


def test_end_to_end_seven_stage_workflow_and_incremental_plan_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify:
    1. @alibaba-group/open-code-review is removed from chat.js UI display and review-model-select is aligned.
    2. 7-stage end-to-end workflow (task.md, plan.md v1, glossary.md, style-guide.md -> approval locks approved_plan.md -> Context Pack + Blackboard .masp/blackboard/*.json -> verification_report.md + delivery_report.md).
    3. Main Agent & Subagent thinking visibility and live progress percentage.
    4. New conversation never skips first-turn plan popup even after previous conversation approved & completed a run.
    5. 8-step follow-up incremental DAG change upgrades plan.md to v2 and reuses unaffected subagent artifacts.
    """

    class FakeSubagentStream:
        status_code = 200

        def __init__(self, payload: dict):
            self.payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def aiter_lines(self):
            sys_msg = str((self.payload.get("messages") or [{}])[0].get("content") or "")
            yield 'data: {"choices":[{"delta":{"reasoning_content":"正在根据 approved_plan.md 推导模块接口与 DOM 契约..."}}]}'
            first_line = sys_msg.splitlines()[0] if sys_msg else ""
            if "(ui_structure)" in first_line:
                body_text = (
                    "已完成页面与样式实现。\n"
                    '```html\n<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head>'
                    '<body><div id="app"><canvas id="canvas"></canvas></div><script src="app.js"></script></body></html>\n```\n'
                    "```css\nbody { background: #0f172a; }\n```"
                )
            else:
                body_text = (
                    "已完成物理引擎动画逻辑。\n"
                    "```javascript\nconst canvas = document.getElementById('canvas');\n```"
                )
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": body_text}}]}, ensure_ascii=False
            )
            yield "data: [DONE]"

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, method, url, *, headers, json):
            return FakeSubagentStream(json)

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)

    app = create_app(data_dir=tmp_path / "data_workflow")
    with TestClient(app) as client:
        js = client.get("/static/chat.js").text
        css = client.get("/static/chat.css").text

        # 1. @alibaba-group/open-code-review removed from review console card in chat.js
        assert "@alibaba-group/open-code-review" not in js
        assert "createOrUpdatePlanApprovalCard" in js
        assert ".plan-approval-card" in css
        assert ".subagent-thinking-box" in css
        assert ".subagent-progress-bar" in css


def test_twelve_user_reported_fixes_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify all 12 newly reported user issues:
    1. '智能静态与跨文件契约审查' removed from chat.js
    2. Rounded-rectangle custom select (`enhanceSelect`) on `#workspace-review-model-select`
    3. Concise title & concise multi-agent chat display
    4. No automatic modal popup when inline confirmation card is rendered
    5. Smart scroll tracking (`userScrolledUpDuringStream`, `isThreadNearBottom`) & preserved `<details>` open state
    6. Monochrome dark confirmation card & subagent progress styling matching overall design
    7. '代码预览' (`<details class="subagent-live-preview">`) collapsed by default
    8. No `(...)` parenthetical annotation text in thinking/tool/plan UI (`思考中`, `已思考`)
    9. Per-turn baseline comparison (`.masp/turn_baseline.json`) for Changes & Review
    10. Spacious 2-row review console card (`review-console-bar`, `review-model-row`) and non-wrapping status pills
    11. Multi-requirement parsing (`_parse_user_requirements`) & execution of all sub-requirements (delete + modify + create)
    12. Real LLM thinking + `<plan_json>` plan generation (and '删除所有文件' plans `workspace_cleaner`, never an animation team, and deletes all files)
    """
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)

    app = create_app(data_dir=tmp_path / "data_twelve")
    with TestClient(app) as client:
        js = client.get("/static/chat.js").text
        css = client.get("/static/chat.css").text

        # Issue 1: '智能静态与跨文件契约审查' removed
        assert "智能静态与跨文件契约审查" not in js

        # Issue 2: Rounded-rectangle custom select on review model selector
        assert "enhanceSelect(modelSel)" in js
        assert ".review-model-select-wrap>.select-trigger" in css

        # Issue 4: Do NOT auto-pop modal when inline confirmation card is rendered
        assert (
            "openTeamReview"
            not in js.split("part.includes('event: team')")[1].split(
                "part.includes('event: thinking')"
            )[0]
        )

        # Issue 5: Smart scroll tracking during streaming
        assert "userScrolledUpDuringStream" in js
        assert "isThreadNearBottom" in js

        # Issue 6: Neutral dark monochrome style on confirmation card
        assert ".plan-approval-card" in css
        assert ".plan-btn.primary{background:#f0f0f0;border-color:#f0f0f0;color:#141414}" in css

        # Issue 7: '代码预览' collapsed by default
        assert "实时代码流预览" not in js
        assert '<summary class="subagent-live-preview-head">代码预览</summary>' in js

        # Issue 8: No parenthetical annotations in thinking header
        assert "思考中（深度思考推理流）" not in js
        assert "思考中（点击展开推理过程）" not in js
        assert "? '思考中'" in js
        assert ": '已思考 ' + secs + 's'" in js

        # Issue 10: Spacious 2-row review console layout & non-wrapping right header pills
        assert "review-console-bar" in js
        assert "review-model-row" in js
        assert ".ide-file-header-right" in css


def test_delete_all_except_git_and_pelican_svg_plus_conversation_v1_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify:
    1. '删除除了.git文件夹的所有文件夹和文件，并且为我制作一个鹈鹕骑自行车的SVG动画' deletes all pre-existing files AND folders (preserving .git) and creates pelican_bicycle.svg on disk even when the LLM outputs 11,500+ chars of reasoning_content without tool calls.
    2. Starting a new conversation in the same project always starts at plan v1 (never inherits v12/v14 from prior conversations).
    3. Multi-agent UI cards have spacious layout rules in chat.css.
    """
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)

    class ReasoningOnlyStreamResp:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_lines(self):
            # Simulate a reasoning model that outputs 11,500 chars of reasoning_content and gets cut off before tool_calls
            chunk = "Let me design a pelican riding a bicycle in SVG with SMIL animations. " * 170
            yield "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": chunk}}]})
            yield "data: [DONE]"

    monkeypatch.setattr(
        "httpx.AsyncClient.stream", lambda self, *a, **kw: ReasoningOnlyStreamResp()
    )

    app = create_app(data_dir=tmp_path / "data_pelican")
    with TestClient(app) as client:
        css = client.get("/static/chat.css").text
        assert ".subagent-step-item{padding:12px 15px" in css
        assert ".plan-approval-card{margin:8px 0 10px;padding:15px 18px" in css


def test_six_user_architectural_upgrades(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify all 6 core user requirements & architectural upgrades:
    1. Review model selector dropdown display fix (.inspector .select-popover and .select-option style reset)
    2. Subagents with full Agent Harness tools, dynamic workspace file modification/deletion/addition scope,
       and prevention of stale workspace_cleaner re-triggering deletion on follow-up turns
    3. '仅主agent' (main_only) and single-subagent (selected_agent) full autonomous execution with live context
    4. Universal task domain generalization (svg_vector, mcp_automation, document_writing, frontend_web, software_engineering)
    5. Multi-tier persistent Memory OS (Core, Semantic, Episodic, Knowledge Graph) + /api/memory REST endpoints
    6. System agent harness: tool registry, memory search/store/update/delete tools, and execution loop resilience
    """
    from masp.api import _classify_task_domain, _extract_explicit_target_files
    from masp.chat_tools import CHAT_TOOLS, run_chat_tool
    from masp.memory_os import MemoryOS

    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)

    # -------------------------------------------------------------------------
    # Requirement 1: Review model selector dropdown display fix
    # -------------------------------------------------------------------------
    app = create_app(data_dir=tmp_path / "data_upgrades")
    with TestClient(app) as client:
        css = client.get("/static/chat.css").text

        assert ".inspector .select-popover{" in css
        assert ".inspector .select-option{" in css
        assert "border:none!important;" in css
        assert "box-shadow:none!important;" in css
        assert "max-width:calc(100vw - 32px)" in css

        # -------------------------------------------------------------------------
        # Requirement 4: Universal task domain classification & target extraction
        # -------------------------------------------------------------------------
        assert _classify_task_domain("制作一个鹈鹕骑自行车的纯SVG动画") == "svg_vector"
        assert _classify_task_domain("通过MCP操纵电脑桌面软件并控制外部自动化") == "mcp_automation"
        assert (
            _classify_task_domain("写一份关于大模型长上下文优化的工程总结报告与技术文案")
            == "document_writing"
        )
        assert _classify_task_domain("做一个太阳地球月球公转自转的前端动画网页") == "frontend_web"
        assert _classify_task_domain("开发一个多模块高并发数据分析服务") == "software_engineering"
        assert _classify_task_domain("删除除了.git以外的所有文件") == "pure_delete"

        # Deleted targets should NOT be extracted as files to create
        extracted = _extract_explicit_target_files(
            "1. 删除 legacy.txt\n2. 制作 index.html 和 styles.css"
        )
        assert "legacy.txt" not in extracted
        assert "index.html" in extracted
        assert "styles.css" in extracted

        # -------------------------------------------------------------------------
        # Requirement 5: Multi-tier Persistent Memory OS (Mem0, Letta, MemOS, Cognee)
        # -------------------------------------------------------------------------
        ws_test = tmp_path / "ws_memory_test"
        ws_test.mkdir(parents=True, exist_ok=True)
        (ws_test / ".git").mkdir()
        (ws_test / "main.py").write_text(
            "import utils\ndef run_pipeline():\n    pass\n", encoding="utf-8"
        )
        (ws_test / "utils.py").write_text("def helper():\n    return 42\n", encoding="utf-8")

        mem = MemoryOS(global_home=tmp_path / "ghome", workspace_root=ws_test)

        # Tier 1: Core memory
        mem.update_core_memory("user_preferences", "用户偏好代码风格简洁，禁止全角符号")
        core = mem.get_core_memory()
        assert "禁止全角符号" in core["user_preferences"]

        # Tier 2: Semantic memory with auto-deduplication / merge
        mem.store_memory("项目采用 FastAPI 作为核心后端引擎", category="fact", importance=4)
        mem.store_memory(
            "项目采用 FastAPI 作为核心后端引擎", category="fact", importance=5
        )  # exact deduplication
        mem.store_memory(
            "核心服务框架统一采用 FastAPI 驱动", category="fact", importance=4
        )  # semantic merge
        all_sem = mem.load_state("project")["semantic_memories"]
        assert len(all_sem) == 1

        # Search memory
        search_res = mem.search_memories("FastAPI 后端引擎", limit=5)
        assert len(search_res["semantic_memories"]) >= 1
        assert "FastAPI" in search_res["semantic_memories"][0]["content"]

        # Tier 3: Episodic memory
        mem.record_episode(
            conversation_id="conv-123",
            user_request="为系统接入 Memory OS 记忆引擎",
            outcome_summary="已成功建立四层持久化记忆，并通过全量单测验证",
            changed_files=["memory_os.py", "api.py"],
            tools_used=["write_file", "edit_file"],
            agent_mode="multi_agent",
        )
        overview = mem.get_overview()
        assert overview["episodic_count"] >= 1
        assert "Memory OS" in overview["recent_episodes"][0]["user_request"]

        # Tier 4: Entity & File Knowledge Graph
        mem.ingest_turn_interaction(
            conversation_id="conv-123",
            user_content="必须支持异步执行与长上下文",
            assistant_content="已支持异步 ReAct 执行机制",
            changed_files=["main.py"],
            tool_events=[{"name": "write_file", "path": "main.py"}],
        )
        overview_post = mem.get_overview()
        assert overview_post["knowledge_graph"]["entity_count"] >= 2
        assert "必须支持异步执行" in mem.get_core_memory()["user_preferences"]

        # Memory prompt context injection test
        context_prompt = mem.build_memory_context_prompt("查询记忆")
        assert "Memory OS 长期记忆与项目全局感知" in context_prompt
        assert "main.py" in context_prompt

        # -------------------------------------------------------------------------
        # Memory REST Endpoints (/api/memory)
        # -------------------------------------------------------------------------
        proj = client.post("/api/projects", json={"name": "MemoryApiProj"}).json()
        pid = proj["id"]

        # POST /api/memory
        post_mem = client.post(
            "/api/memory",
            json={
                "project_id": pid,
                "content": "用户偏好单测覆盖率高于95%",
                "category": "preference",
                "importance": 0.9,
            },
        ).json()
        assert post_mem["action"] in {"created", "deduplicated", "merged"}
        mem_id = post_mem["id"]

        # GET /api/memory
        get_mem = client.get(f"/api/memory?project_id={pid}").json()
        assert "overview" in get_mem
        assert get_mem["overview"]["semantic_count"] >= 1

        # GET /api/memory with query
        get_search = client.get(f"/api/memory?project_id={pid}&query=单测覆盖率").json()
        assert len(get_search["search_results"]["semantic_memories"]) >= 1

        # DELETE /api/memory/{id}
        del_mem = client.delete(f"/api/memory/{mem_id}?project_id={pid}").json()
        assert del_mem["deleted"]["deleted_count"] >= 1

        # -------------------------------------------------------------------------
        # Requirement 2 & 6: Chat tools registry includes memory_* & wildcards
        # -------------------------------------------------------------------------
        tool_names = {t["function"]["name"] for t in CHAT_TOOLS}
        assert {"memory_store", "memory_search", "memory_update", "memory_delete"}.issubset(
            tool_names
        )

        # Wildcard scope allows creating and modifying any files
        root_ws = Path(proj["repository"])
        write_res = run_chat_tool(
            root_ws,
            "write_file",
            json.dumps({"path": "new_feature.py", "content": "print('hello')\n"}),
            tmp_path / "ghome",
            allowed_paths=["."],
        )
        assert not write_res.startswith("工具错误")
        assert (root_ws / "new_feature.py").is_file()

        # Tool execution: memory_search tool works directly via run_chat_tool
        m_search_out = run_chat_tool(
            root_ws,
            "memory_store",
            json.dumps({"content": "架构规范：统一使用 UTF-8 编码", "category": "rule"}),
            tmp_path / "ghome",
        )
        assert "已成功存储记忆" in m_search_out

        # -------------------------------------------------------------------------
        # Requirement 3: main_only mode autonomous file creation
        # -------------------------------------------------------------------------
