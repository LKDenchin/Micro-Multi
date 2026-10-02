"""Behavioral regressions for lead-owned collaboration, using deterministic providers."""

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from masp.api import create_app
from masp.chat_tools import CHAT_TOOLS
from masp.supervisor import SupervisorManager


class Response:
    status_code = 200

    def __init__(self, delta=None, status=200):
        self.delta = delta or {}
        self.status_code = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def aread(self):
        return b"provider unavailable"

    async def aiter_lines(self):
        yield "data:" + json.dumps({"choices": [{"delta": self.delta}]})
        yield "data: [DONE]"


def call(name, arguments):
    return {
        "index": 0,
        "id": "call-1",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


@pytest.mark.parametrize("mode", [None, "main_only"])
@pytest.mark.parametrize("prompt", ["什么是递归？", "解释以下理论。" * 100])
def test_questions_answer_without_team_or_project_tools(tmp_path, monkeypatch, mode, prompt):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)
    requests = []

    def stream(self, *a, **kw):
        requests.append(kw["json"])
        return Response({"content": "递归是函数调用自身。"})

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)

    # Title generation is ancillary and should not require a live provider.
    async def no_title(*a, **kw):
        raise RuntimeError("no title endpoint")

    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "mock", "model": "mock", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        project = client.post("/api/projects", json={"name": "Questions"}).json()
        root = Path(project["repository"])
        (root / "existing.py").write_text("print(1)", encoding="utf-8")

        def unexpected_scan(*a, **kw):
            raise AssertionError("问答不应扫描工作区")

        monkeypatch.setattr("masp.api.os.walk", unexpected_scan)
        conv = client.post(
            "/api/conversations",
            json={"project_id": project["id"], "model_profile_id": profile["id"]},
        ).json()
        result = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"content": prompt, "agent_id": mode, "access_mode": "commands"},
        )
        assert "递归是函数调用自身" in result.text
        assert "event: tool" not in result.text
        assert ("event: team" in result.text) == (mode is None)
        assert "event: execution_plan" not in result.text
        assert not (root / "plan.md").exists()
        assert not (root / "SHARED_DEV_SPEC.md").exists()
        assert len(requests) == 1 if mode == "main_only" else len(requests) >= 2


def config():
    return SimpleNamespace(
        model="mock", api_key="", base_url="http://mock/v1", temperature=0, max_output_tokens=4096
    )


def test_unscoped_blocking_commands_serialize_and_return_evidence(tmp_path, monkeypatch):
    import time

    active = 0
    peak = 0
    counter_lock = threading.Lock()

    def tool(**kwargs):
        nonlocal active, peak
        with counter_lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.04)
        with counter_lock:
            active -= 1
        return json.dumps({"exit_code": 0, "stdout": "passed"})

    monkeypatch.setattr("masp.supervisor.run_chat_tool", tool)

    class Client:
        def stream(self, *a, **kw):
            if kw["json"]["messages"][-1]["role"] == "tool":
                return Response({"content": "测试通过"})
            return Response({"tool_calls": [call("run_command", {"command": "test"})]})

    async def run():
        mgr = SupervisorManager(tmp_path, "parallel", max_concurrency=2)
        events = []

        async def emit(kind, data):
            events.append((kind, dict(data)))

        kwargs = dict(
            client=Client(),
            default_config=config(),
            load_model_config=lambda _: config(),
            sub_tools=CHAT_TOOLS,
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
            max_turns=3,
        )
        reports = await asyncio.gather(
            *(mgr.execute_subagent_task(name, "运行测试", **kwargs) for name in ("one", "two"))
        )
        assert all(r["status"] == "completed" for r in reports)
        assert all(r["tool_call_count"] == 1 for r in reports)
        assert len([e for e in events if e[0] == "tool"]) == 2
        assert peak == 1  # opaque commands do not race in a shared workspace

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["http", "empty", "budget", "command"])
def test_worker_failure_is_never_completion(tmp_path, failure):
    class Client:
        def stream(self, *a, **kw):
            if failure == "http":
                return Response(status=503)
            if failure == "empty":
                return Response()
            if kw["json"]["messages"][-1]["role"] == "tool" and failure == "command":
                return Response({"content": "完成"})
            return Response({"tool_calls": [call("run_command", {"command": "bad"})]})

    async def run():
        async def execute(*a):
            return '{"exit_code": 7, "stderr": "failure"}'

        async def emit(*a):
            pass

        mgr = SupervisorManager(tmp_path, "failure", tool_executor=execute)
        report = await mgr.execute_subagent_task(
            "worker",
            "验证",
            client=Client(),
            default_config=config(),
            load_model_config=lambda _: config(),
            sub_tools=CHAT_TOOLS,
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
            max_turns=2,
        )
        assert report["status"] == "failed"
        assert report["error"]
        assert mgr.subagents["worker"].progress_pct < 100

    asyncio.run(run())


def test_worker_history_and_user_edits_survive_resume_and_next_dispatch(tmp_path):
    async def run():
        requests = []

        class Client:
            def stream(self, *a, **kw):
                requests.append(json.loads(json.dumps(kw["json"])))
                return Response({"content": "收到最新职责"})

        async def emit(*a):
            pass

        mgr = SupervisorManager(
            tmp_path, "history", parent_context=[{"role": "user", "content": "用户的完整原始意图"}]
        )
        mgr.create_subagent("worker", "分析", "自主调查")
        pause = asyncio.Event()
        pause.set()
        kwargs = dict(
            client=Client(),
            default_config=config(),
            load_model_config=lambda _: config(),
            sub_tools=CHAT_TOOLS,
            cancel_event=asyncio.Event(),
            pause_event=pause,
            emit_event=emit,
            max_turns=3,
        )
        task = asyncio.create_task(mgr.execute_subagent_task("worker", "第一项任务", **kwargs))
        await asyncio.sleep(0.02)
        mgr.apply_team_update(
            {
                "agents": [
                    {"id": "worker", "responsibility": "新的职责", "system_prompt": "检查边界条件"}
                ]
            }
        )
        pause.clear()
        assert (await task)["status"] == "completed"
        assert "检查边界条件" in requests[0]["messages"][0]["content"]
        restored = SupervisorManager(tmp_path, "history", initial_team=mgr.team_obj)
        await restored.execute_subagent_task("worker", "第二项任务", **kwargs)
        assert any(m.get("content", "").endswith("第一项任务\n") for m in requests[1]["messages"])
        assert requests[1]["messages"][-1]["content"].endswith("第二项任务\n")

    asyncio.run(run())


def test_lead_parallel_delivery_and_actual_integration_check(tmp_path, monkeypatch):
    """A lead selects arbitrary members and paths, then verifies their joint output."""
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)
    receipts = []

    def stream(self, *a, **kw):
        messages = kw["json"]["messages"]
        last = messages[-1]
        system = messages[0]["content"]
        if "(task_worker)" in system:
            return Response({"content": "建议将 a、b 两个独立模块分工实现，并验证求和结果。"})
        if "自主子代理" in system:
            if last["role"] == "tool":
                return Response({"content": "已写入模块，交回主代理验收"})
            name = "a" if "(alpha)" in system else "b"
            return Response(
                {
                    "tool_calls": [
                        call(
                            "write_file",
                            {
                                "path": f"{name}.py",
                                "content": f"value = {1 if name == 'a' else 2}\n",
                            },
                        )
                    ]
                }
            )
        if last["role"] == "user":
            return Response(
                {
                    "tool_calls": [
                        call(
                            "dispatch_subagents_parallel",
                            {
                                "tasks": [
                                    {"subagent_name": "alpha", "prompt": "自主创建 a.py 模块"},
                                    {"subagent_name": "beta", "prompt": "自主创建 b.py 模块"},
                                ]
                            },
                        )
                    ]
                }
            )
        if "parallel_reports" in last.get("content", ""):
            return Response(
                {
                    "tool_calls": [
                        call(
                            "run_command",
                            {
                                "command": "python -c \"import a,b; assert a.value+b.value == 3; print('integration passed')\""
                            },
                        )
                    ]
                }
            )
        receipts.append(last["content"])
        return Response({"content": "两个模块已交付，集成验证通过。"})

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)

    async def no_title(*a, **kw):
        raise RuntimeError("no title endpoint")

    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "mock", "model": "mock", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        project = client.post("/api/projects", json={"name": "Delivery"}).json()
        conv = client.post(
            "/api/conversations",
            json={"project_id": project["id"], "model_profile_id": profile["id"]},
        ).json()
        response = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"content": "开发两个模块并进行集成验证", "access_mode": "commands"},
        )
        assert "集成验证通过" in response.text, response.text
        assert any("integration passed" in receipt for receipt in receipts)
        root = Path(project["repository"])
        assert (root / "a.py").read_text() == "value = 1\n"
        assert (root / "b.py").read_text() == "value = 2\n"
        team = client.app.state.service.store.get("conversation", conv["id"])["team"]
        assert {a["id"] for a in team["agents"]} == {"task_worker", "alpha", "beta"}
        assert all(a["owned_paths"] == [] for a in team["agents"])
        assert set(team["histories"]) == {"task_worker", "alpha", "beta"}
        # Individual workers cannot be addressed as a third user-facing mode.
        rejected = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"content": "你好", "agent_id": "alpha"},
        )
        assert rejected.status_code == 422
