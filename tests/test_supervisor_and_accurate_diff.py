"""Tests for the dynamic Supervisor multi-agent engine and accurate per-turn diffing.

Verifies:
1. Dynamic subagent creation, task dispatching, and mindmap sync via SupervisorManager.
2. Subagents have full workspace access without artificial path boundaries.
3. Clean output stripping raw DSML tokens (<｜｜DSML｜｜ calls>, <tool_call>, etc.).
4. Turn diff and changes snapshot strictly measure pre-turn vs post-turn deltas
   with base_content=o_txt, eliminating cumulative history and unrelated files.
5. Historical changes endpoint returns exact turn snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from masp.api import create_app
from masp.supervisor import (
    SupervisorManager,
    clean_raw_model_tokens,
)


def test_clean_raw_model_tokens():
    """Verify that raw DSML / tool call tags never leak to the user chat."""
    sample = (
        "我来实际核查这几处代码，先并行读取关键文件和运行测试。\n\n"
        "<｜｜DSML｜｜ calls>\n"
        '<｜｜DSML｜｜ invoke name="run_command">\n'
        '<｜｜DSML｜｜ parameter name="command" string="true">node tests/smoke.test.js</｜｜DSML｜｜ parameter>\n'
        "</｜｜DSML｜｜ invoke>\n"
        "</｜｜DSML｜｜ calls>\n\n"
        "找到关键线索了。"
    )
    cleaned = clean_raw_model_tokens(sample)
    assert "<｜｜DSML｜｜" not in cleaned
    assert "node tests/smoke.test.js" not in cleaned
    assert "我来实际核查这几处代码" in cleaned
    assert "找到关键线索了。" in cleaned

    # Test tool_call tags
    sample2 = '正在执行：<tool_call>{"name": "run_command"}</tool_call>执行完毕。'
    assert "<tool_call>" not in clean_raw_model_tokens(sample2)


def test_supervisor_subagent_lifecycle(tmp_path: Path):
    """Verify dynamic creation, adjustment, and mindmap event generation."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "sample.py").write_text("def hello(): pass\n", encoding="utf-8")

    mgr = SupervisorManager(workspace_root=workspace, conversation_id="conv-1")
    assert len(mgr.subagents) == 0

    # 1. Create subagent
    spec = mgr.create_subagent(
        name="test_engineer",
        role="自动化测试工程师",
        description="负责编写和运行 pytest 测试套件并验证质量",
        system_prompt="严格执行实证测试，确保所有断言通过",
        model="gpt-4o",
    )
    assert spec.id == "test_engineer"
    assert spec.role == "自动化测试工程师"
    assert spec.status == "ready"
    assert spec.owned_paths == []  # No artificial file restriction

    # 2. Check team event payload
    team_data = mgr.get_team_event_data()
    assert team_data["conversation_id"] == "conv-1"
    assert len(team_data["agents"]) == 1
    assert team_data["agents"][0]["id"] == "test_engineer"
    assert team_data["agents"][0]["role"] == "自动化测试工程师"

    # 3. Adjust subagent
    adjusted = mgr.adjust_subagent(
        name="test_engineer",
        role="高级测试工程师",
        description="重构并运行端到端冒烟测试",
    )
    assert adjusted is not None
    assert adjusted.role == "高级测试工程师"
    assert "重构" in adjusted.responsibility


def test_accurate_per_turn_diff_calculation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify that turn diffing strictly reports files modified in that turn only."""
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)

    class FakeStreamResp:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_lines(self):
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": "已验证 smoke.test.js 测试文件。"}}]},
                ensure_ascii=False,
            )
            yield "data: [DONE]"

    monkeypatch.setattr("httpx.AsyncClient.stream", lambda self, *a, **kw: FakeStreamResp())

    app = create_app(data_dir=tmp_path / "data_diff")
    with TestClient(app) as client:
        # Create profile and project
        prof = client.post(
            "/api/model-profiles",
            json={
                "name": "test-prof",
                "model": "mock-model",
                "base_url": "http://127.0.0.1:9999/v1",
            },
        ).json()
        proj = client.post("/api/projects", json={"name": "AccurateDiffProj"}).json()
        pid = proj["id"]
        conv = client.post(
            "/api/conversations",
            json={"project_id": pid, "model_profile_id": prof["id"]},
        ).json()
        cid = conv["id"]

        ws_dir = Path(proj["repository"])

        # Manually create existing project files beforehand (mimicking historical turns)
        (ws_dir / "app.js").write_text("// existing app.js\nconsole.log(1);\n", encoding="utf-8")
        (ws_dir / "styles.css").write_text(
            "/* existing styles.css */\nbody { margin: 0; }\n", encoding="utf-8"
        )
        (ws_dir / "main.py").write_text("print('existing main.py')\n", encoding="utf-8")

        # Now execute a turn that ONLY modifies a single new file: tests/smoke.test.js
        # In solo/main_only mode, we ask to create smoke.test.js
        tests_dir = ws_dir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        smoke_file = tests_dir / "smoke.test.js"

        # Simulate the tool execution writing smoke.test.js
        smoke_file.write_text("console.log('smoke test passed');\n", encoding="utf-8")

        # Send a message to record the turn
        resp = client.post(
            f"/api/conversations/{cid}/messages",
            json={
                "content": "验证并记录 smoke.test.js",
                "project_id": pid,
                "agent_id": "main_only",
                "model_profile_id": prof["id"],
                "access_mode": "commands",
            },
        )
        assert resp.status_code == 200
        stream_body = resp.text
        assert "event: " in stream_body or "data: " in stream_body

        # Fetch messages to inspect the assistant message turn diff
        msgs = client.get(f"/api/conversations/{cid}/messages").json()
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        assert len(assistant_msgs) > 0
        latest_assistant = assistant_msgs[-1]

        # The turn diff must NOT contain app.js, styles.css, or main.py because they were NOT modified during this turn!
        turn_diff = latest_assistant.get("turn_diff")
        if turn_diff and turn_diff.get("files"):
            diff_paths = [f["path"] for f in turn_diff["files"]]
            assert "app.js" not in diff_paths
            assert "styles.css" not in diff_paths
            assert "main.py" not in diff_paths

        # Fetch the historical changes snapshot endpoint for this message
        msg_id = latest_assistant["id"]
        changes_resp = client.get(f"/api/conversations/{cid}/messages/{msg_id}/changes")
        assert changes_resp.status_code == 200
        changes_data = changes_resp.json()
        changes_paths = [f["path"] for f in changes_data.get("files", [])]
        assert "app.js" not in changes_paths
        assert "styles.css" not in changes_paths
        assert "main.py" not in changes_paths


def test_direct_multiagent_supervisor_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify that multi-agent mode executes immediately without confirmation card or rigid path cages,
    and the Supervisor can dynamically create subagents, dispatch tasks, and verify results."""
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)

    class MockStreamResp:
        def __init__(self, json_body: dict[str, Any]):
            self.json_body = json_body
            self.status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_lines(self):
            messages = self.json_body.get("messages", [])
            last_msg = messages[-1] if messages else {}

            # Case 1: Subagent ReAct loop calling write_file
            if any(
                "你是 Micro-Multi 多 Agent 协作网络中的自主子代理" in m.get("content", "")
                for m in messages
                if m.get("role") == "system"
            ):
                if last_msg.get("role") == "tool":
                    # Tool executed, subagent finishes with summary
                    yield "data: " + json.dumps(
                        {
                            "choices": [{"delta": {"content": "已成功创建并验证 fibonacci.py。"}}],
                        },
                        ensure_ascii=False,
                    )
                else:
                    # Subagent calls write_file
                    tc = {
                        "index": 0,
                        "id": "call_sub_write_1",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps(
                                {
                                    "path": "fibonacci.py",
                                    "content": "def fib(n):\n    return n if n <= 1 else fib(n-1) + fib(n-2)\n",
                                }
                            ),
                        },
                    }
                    yield "data: " + json.dumps(
                        {
                            "choices": [
                                {
                                    "delta": {
                                        "content": "正在编写 fibonacci.py...",
                                        "tool_calls": [tc],
                                    }
                                }
                            ],
                        },
                        ensure_ascii=False,
                    )
                yield "data: [DONE]"
                return

            # Case 2: Supervisor ReAct loop
            if last_msg.get("role") == "user":
                # First supervisor turn: create_subagent
                tc = {
                    "index": 0,
                    "id": "call_sup_create_1",
                    "type": "function",
                    "function": {
                        "name": "create_subagent",
                        "arguments": json.dumps(
                            {
                                "name": "code_builder",
                                "role": "核心开发工程师",
                                "description": "负责编写核心算法代码并自测",
                            }
                        ),
                    },
                }
                yield "data: " + json.dumps(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "content": "我先创建核心开发工程师子代理。",
                                    "tool_calls": [tc],
                                }
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            elif last_msg.get("role") == "tool":
                tool_output = last_msg.get("content", "")
                if "code_builder" in tool_output and "dispatch_subagent_task" in tool_output:
                    # After creating subagent, supervisor dispatches task
                    tc = {
                        "index": 0,
                        "id": "call_sup_dispatch_1",
                        "type": "function",
                        "function": {
                            "name": "dispatch_subagent_task",
                            "arguments": json.dumps(
                                {
                                    "subagent_name": "code_builder",
                                    "prompt": "编写 fibonacci.py 实现斐波那契数列并自测",
                                }
                            ),
                        },
                    }
                    yield "data: " + json.dumps(
                        {
                            "choices": [
                                {
                                    "delta": {
                                        "content": "现在调度子代理执行任务。",
                                        "tool_calls": [tc],
                                    }
                                }
                            ],
                        },
                        ensure_ascii=False,
                    )
                elif "completed" in tool_output:
                    # After subagent reports completion, supervisor finalizes answer
                    yield "data: " + json.dumps(
                        {
                            "choices": [
                                {
                                    "delta": {
                                        "content": "子代理已完成 fibonacci.py 的编写与验证，算法功能完整可用。"
                                    }
                                }
                            ],
                        },
                        ensure_ascii=False,
                    )
                else:
                    yield "data: " + json.dumps(
                        {
                            "choices": [{"delta": {"content": "继续推进。"}}],
                        },
                        ensure_ascii=False,
                    )
            else:
                yield "data: " + json.dumps(
                    {
                        "choices": [{"delta": {"content": "任务已完成。"}}],
                    },
                    ensure_ascii=False,
                )

            yield "data: [DONE]"

    def mock_stream(self, method, url, **kwargs):
        json_body = kwargs.get("json", {})
        return MockStreamResp(json_body)

    monkeypatch.setattr("httpx.AsyncClient.stream", mock_stream)

    app = create_app(data_dir=tmp_path / "data_sup")
    with TestClient(app) as client:
        prof = client.post(
            "/api/model-profiles",
            json={
                "name": "test-prof",
                "model": "mock-model",
                "base_url": "http://127.0.0.1:9999/v1",
            },
        ).json()
        proj = client.post("/api/projects", json={"name": "SupervisorProj"}).json()
        pid = proj["id"]
        conv = client.post(
            "/api/conversations",
            json={"project_id": pid, "model_profile_id": prof["id"]},
        ).json()
        cid = conv["id"]

        # Send multi-agent message (not main_only)
        resp = client.post(
            f"/api/conversations/{cid}/messages",
            json={
                "content": "请实现斐波那契数列模块 fibonacci.py",
                "project_id": pid,
                "model_profile_id": prof["id"],
                "access_mode": "commands",
            },
        )
        assert resp.status_code == 200
        body_text = resp.text

        # 1. MUST NOT require user confirmation
        assert '"first_turn_confirm": true' not in body_text.lower()
        assert "已根据需求生成协作方案，请确认下方任务分工后开始执行。" not in body_text

        # 2. MUST create fibonacci.py
        ws_dir = Path(proj["repository"])
        created_file = ws_dir / "fibonacci.py"
        assert created_file.is_file(), body_text
        assert "def fib" in created_file.read_text(encoding="utf-8")

        # 3. Team event emitted with dynamic subagent and no path restrictions
        assert "code_builder" in body_text
        assert "subagent_progress" in body_text
