import json
from pathlib import Path

from fastapi.testclient import TestClient

from masp.agents import extract_dsml_tool_calls
from masp.api import create_app
from masp.compaction import ObservationOptimizer
from masp.domain import ExecutionPlan, PlanStep
from masp.memory_os import MemoryOS


def test_dsml_tool_call_extraction_double_fullwidth():
    raw_text = (
        "我来实际核查代码，先并行读取关键文件和运行测试。\n"
        "<｜｜DSML｜｜ calls>\n"
        '<｜｜DSML｜｜ invoke name="run_command">\n'
        '<｜｜DSML｜｜ parameter name="command" string="true">node tests/smoke.test.js</｜｜DSML｜｜ parameter>\n'
        "</｜｜DSML｜｜ invoke>\n"
        "</｜｜DSML｜｜ calls>\n"
        "执行完成。"
    )
    cleaned, calls = extract_dsml_tool_calls(raw_text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "run_command"
    parsed_args = json.loads(calls[0]["function"]["arguments"])
    assert parsed_args["command"] == "node tests/smoke.test.js"
    assert "<｜｜DSML" not in cleaned
    assert "</｜｜DSML" not in cleaned
    assert "node tests/smoke.test.js" not in cleaned
    assert "我来实际核查代码" in cleaned
    assert "执行完成" in cleaned


def test_letta_memory_os_operations(tmp_path: Path):
    mem_os = MemoryOS(tmp_path, project_id="test_proj", workspace_root=tmp_path)

    # Core memory append and replace
    res1 = mem_os.core_memory_append("human", "User prefers Vue 3 and TypeScript.")
    assert "User prefers Vue 3" in res1["content"]
    human_val = mem_os.core_memory_get("human")
    assert "User prefers Vue 3" in human_val

    res2 = mem_os.core_memory_replace(
        "persona", "Senior Lead Architect specializing in high performance.", 0
    )
    assert "Senior Lead Architect" in res2["content"]
    persona_val = mem_os.core_memory_get("persona")
    assert "Senior Lead Architect" in persona_val

    # Archival memory insert & search
    res3 = mem_os.archival_memory_insert(
        "Canvas animation must not be occluded by CSS overlay .fallback."
    )
    assert "Canvas animation" in res3["content"]
    search_res = mem_os.archival_memory_search("Canvas animation")
    assert len(search_res) > 0
    assert any("Canvas animation" in r["content"] for r in search_res)

    # OS process management
    mem_os.register_process(
        "ui_agent", "UI & Canvas Rendering Developer", "gpt-4o", ["index.html", "styles.css"]
    )
    assert mem_os.pause_process("ui_agent") is True
    proc = mem_os.get_process("ui_agent")
    assert proc["state"] == "paused"

    assert (
        mem_os.resume_process(
            "ui_agent", updated_task="Refactor leg kinematics in SVG", updated_route="claude-3-5"
        )
        is True
    )
    proc_resumed = mem_os.get_process("ui_agent")
    assert proc_resumed["state"] == "running"
    assert proc_resumed["task"] == "Refactor leg kinematics in SVG"
    assert proc_resumed["route"] == "claude-3-5"

    overview = mem_os.get_context_overview()
    assert "core_memory" in overview
    assert "total_tokens" in overview


def test_acon_observation_optimizer():
    opt = ObservationOptimizer(max_lines=30)

    # Test log with pytest error
    raw_log = (
        "rootdir: /app\ncollected 50 items\n"
        + "test_file.py .............\n" * 40
        + "FAILED test_file.py::test_fail - AssertionError: canvas not mounted\n=== 1 failed, 49 passed in 2.5s ==="
    )
    compressed = opt.optimize("pytest tests", raw_log)
    assert "AssertionError: canvas not mounted" in compressed
    assert len(compressed.splitlines()) <= 32


def test_execution_plan_domain_validation():
    step1 = PlanStep(step_number=1, title="分析问题与定位CSS覆盖层", target_files=["styles.css"])
    step2 = PlanStep(
        step_number=2,
        title="补全 pelican_bicycle.svg 矢量主体",
        target_files=["pelican_bicycle.svg"],
    )
    plan = ExecutionPlan(
        plan_id="plan_test_001",
        title="Canvas 与 SVG 动画修复计划",
        goal="彻底解决遮罩遮挡与矢量图残缺问题",
        steps=[step1, step2],
        requires_subagents=True,
    )
    assert plan.plan_id == "plan_test_001"
    assert len(plan.steps) == 2
    assert plan.status == "waiting_approval"


def test_pause_resume_and_changes_endpoints(tmp_path: Path):
    app = create_app(tmp_path / "api")
    with TestClient(app) as client:
        store = client.app.state.service.store

        # Create project and conversation
        store.put(
            "project",
            {
                "id": "proj-1",
                "name": "Test Project",
                "repository": str(tmp_path),
                "state": "idle",
                "created_at": "2026-10-01T00:00:00Z",
            },
        )
        store.put(
            "conversation",
            {
                "id": "conv-1",
                "project_id": "proj-1",
                "title": "测试对话",
                "message_count": 1,
                "team": {
                    "agents": [
                        {
                            "id": "sub_1",
                            "name": "子代理1",
                            "model": "env-default",
                            "task": "原始任务",
                        }
                    ],
                    "workflow_state": "running",
                },
                "created_at": "2026-10-01T00:00:00Z",
            },
        )

        # Test pause endpoint
        res_pause = client.post("/api/conversations/conv-1/pause", json={})
        assert res_pause.status_code == 200
        assert res_pause.json()["status"] == "paused"
        updated_conv = store.get("conversation", "conv-1")
        assert updated_conv["team"]["workflow_state"] == "paused"

        # Test resume endpoint with updated subagent routing model and task
        res_resume = client.post(
            "/api/conversations/conv-1/resume",
            json={
                "subagents": [
                    {
                        "id": "sub_1",
                        "name": "子代理1",
                        "model": "deepseek-coder",
                        "task": "调整后的新任务",
                    }
                ]
            },
        )
        assert res_resume.status_code == 200
        assert res_resume.json()["status"] == "running"
        resumed_conv = store.get("conversation", "conv-1")
        assert resumed_conv["team"]["workflow_state"] == "running"
        assert resumed_conv["team"]["agents"][0]["model"] == "deepseek-coder"
        assert resumed_conv["team"]["agents"][0]["task"] == "调整后的新任务"

        # Test per-turn historical changes snapshot endpoint
        store.put(
            "message",
            {
                "id": "msg-turn-1",
                "conversation_id": "conv-1",
                "role": "assistant",
                "content": "已完成修改",
                "turn_diff": {
                    "files_changed": 1,
                    "added": 10,
                    "removed": 2,
                    "files": [{"path": "styles.css", "added": 10, "removed": 2}],
                },
                "turn_changes": {
                    "message_id": "msg-turn-1",
                    "conversation_id": "conv-1",
                    "status": "M  styles.css",
                    "diff": "--- a/styles.css\n+++ b/styles.css\n@@ -1 +1 @@\n-display:flex\n+[hidden]{display:none}",
                    "files": [
                        {
                            "path": "styles.css",
                            "status": "M",
                            "status_label": "修改",
                            "added": 10,
                            "removed": 2,
                            "diff": "@@ -1 +1 @@",
                        }
                    ],
                    "summary": {"files_changed": 1, "added": 10, "removed": 2},
                },
                "created_at": "2026-10-01T00:01:00Z",
            },
            "conv-1",
        )

        res_chg = client.get("/api/conversations/conv-1/messages/msg-turn-1/changes")
        assert res_chg.status_code == 200
        chg_json = res_chg.json()
        assert chg_json["message_id"] == "msg-turn-1"
        assert len(chg_json["files"]) == 1
        assert chg_json["files"][0]["path"] == "styles.css"
        assert chg_json["summary"]["added"] == 10


def test_lengthy_requirement_executes_without_approval(tmp_path: Path, monkeypatch):
    from test_autonomous_collaboration import Response

    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)
    monkeypatch.setattr(
        "httpx.AsyncClient.stream", lambda *a, **kw: Response({"content": "执行请求已收到"})
    )

    async def no_title(*a, **kw):
        raise RuntimeError("no title endpoint")

    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    app = create_app(tmp_path / "api_deer")
    with TestClient(app) as client:
        store = client.app.state.service.store
        ws = tmp_path / "ws_deer"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "main.py").write_text("print('hello')", encoding="utf-8")
        store.put(
            "project",
            {
                "id": "proj-deer",
                "name": "DeerFlow Project",
                "repository": str(ws),
                "state": "idle",
                "created_at": "2026-10-01T00:00:00Z",
            },
        )
        store.put(
            "conversation",
            {
                "id": "conv-deer",
                "project_id": "proj-deer",
                "title": "长需求规划对话",
                "message_count": 0,
                "created_at": "2026-10-01T00:00:00Z",
            },
        )
        profile = client.post(
            "/api/model-profiles",
            json={
                "name": "test-prof",
                "model": "deepseek-chat",
                "base_url": "http://127.0.0.1:9999/v1",
            },
        ).json()
        long_requirement = (
            "系统重构与全面工程优化专项需求：\n"
            "1. 审查当前项目的架构与所有核心代码文件，定位所有性能瓶颈与异常点；\n"
            "2. 建立独立的数据流管道与高效的多代理协同执行链路，防止出现执行中断；\n"
            "3. 引入自动化冒烟测试集，包括对 Canvas 动画与 SVG 矢量图的无头高保真校验；\n"
            "4. 补齐所有异常捕获机制与自主纠错闭环逻辑，确保系统可以长时间自主平稳运行。"
        )
        assert len(long_requirement) >= 160
        resp_plan = client.post(
            "/api/conversations/conv-deer/messages",
            json={
                "content": long_requirement,
                "project_id": "proj-deer",
                "model_profile_id": profile["id"],
                "access_mode": "commands",
            },
        )
        assert resp_plan.status_code == 200
        text = resp_plan.text
        assert "event: execution_plan" not in text
        assert "browse_project" not in text
        assert "执行请求已收到" in text
        assert not (ws / "plan.md").exists()
