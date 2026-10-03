"""Completion-order scheduling and lead/worker overlap, with deterministic gates."""

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_autonomous_collaboration import Response, call, config

from masp.api import create_app
from masp.chat_tools import CHAT_TOOLS
from masp.supervisor import SupervisorManager


def test_background_batch_starts_together_collects_first_and_keeps_slow_worker(tmp_path):
    async def run():
        manager = SupervisorManager(tmp_path, "background", max_concurrency=2)
        started = set()
        both_started = asyncio.Event()
        fast = asyncio.Event()
        slow = asyncio.Event()

        async def execute(name, *args, **kwargs):
            started.add(name)
            if len(started) == 2:
                both_started.set()
            await (fast if name == "fast" else slow).wait()
            return {"status": "completed", "subagent_name": name}

        async def emit(*args):
            pass

        manager._execute_subagent_task = execute
        result = manager.start_subagents(
            [{"subagent_name": name, "prompt": "Independent work"} for name in ("slow", "fast")],
            emit_event=emit,
            cancel_event=asyncio.Event(),
        )
        assert result["background"] and not started  # dispatch returns without waiting
        await asyncio.wait_for(both_started.wait(), 1)
        assert (await manager.wait_subagents(0))["pending"] == ["slow", "fast"]
        fast.set()
        first = await manager.wait_subagents(1)
        assert [r["subagent_name"] for r in first["reports"]] == ["fast"]
        assert first["pending"] == ["slow"]
        assert first["reports"][0]["timing"]["queue_seconds"] >= 0
        slow.set()
        assert (await manager.wait_subagents(1))["reports"][0]["subagent_name"] == "slow"
        assert await manager.wait_subagents(0) == {"reports": [], "pending": []}

    asyncio.run(run())


def test_invalid_batch_has_no_partial_start_and_cancel_releases_slots(tmp_path):
    async def run():
        manager = SupervisorManager(tmp_path, "atomic", max_concurrency=1)
        with pytest.raises(ValueError, match="Duplicate"):
            manager.start_subagents(
                [
                    {"subagent_name": "same", "prompt": "one"},
                    {"subagent_name": "SAME", "prompt": "two"},
                ]
            )
        assert not manager.background_tasks and not manager.subagents
        cancel = asyncio.Event()

        async def execute(*args, **kwargs):
            await asyncio.Event().wait()

        async def emit(*args):
            pass

        manager._execute_subagent_task = execute
        manager.start_subagents(
            [{"subagent_name": name, "prompt": "work"} for name in ("one", "two")],
            emit_event=emit,
            cancel_event=cancel,
        )
        await asyncio.sleep(0)
        cancel.set()
        reports = []
        while manager.background_tasks:
            reports.extend((await manager.wait_subagents(1))["reports"])
        assert len(reports) == 2 and all(r["status"] == "cancelled" for r in reports)
        assert not manager.capacity.locked()

    asyncio.run(run())


def test_lead_writes_while_two_workers_run_and_collects_before_final(tmp_path, monkeypatch):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    lead_calls = []
    worker_starts = set()

    async def worker(self, name, *args, **kwargs):
        worker_starts.add(name)
        # Workers cannot finish until the lead executes its own independent tool.
        async with asyncio.timeout(3):
            while not (self.workspace_root / "lead.txt").exists():
                await asyncio.sleep(0.005)
        (self.workspace_root / f"{name}.txt").write_text("worker complete")
        self.subagents[name].status = "completed"
        return {"status": "completed", "subagent_name": name, "summary": "worker complete"}

    monkeypatch.setattr(SupervisorManager, "_execute_subagent_task", worker)

    def stream(self, *args, **kwargs):
        messages = kwargs["json"]["messages"]
        lead_calls.append(json.loads(json.dumps(messages)))
        if len(lead_calls) == 1:
            return Response(
                {
                    "tool_calls": [
                        call("write_file", {"path": "lead.txt", "content": "lead complete"})
                    ]
                }
            )
        # Intentionally omit wait_subagents: the server must collect before closing the turn.
        return Response({"content": "任务完成"})

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)

    async def no_title(*args, **kwargs):
        raise RuntimeError("no title endpoint")

    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    with TestClient(create_app(tmp_path / "home")) as client:
        # This test exercises the retained Python Supervisor implementation;
        # official native parallelism is covered by test_native_chat.py.
        client.put("/api/dsh/settings", json={"agentLoop": {"runtime": "python"}})
        profile = client.post(
            "/api/model-profiles",
            json={"name": "mock", "model": "mock", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        project = client.post("/api/projects", json={"name": "Background"}).json()
        conv = client.post(
            "/api/conversations",
            json={"project_id": project["id"], "model_profile_id": profile["id"]},
        ).json()
        team = client.put(
            f"/api/projects/{project['id']}/team",
            json={
                "conversation_id": conv["id"],
                "requirement": "Implement independent modules",
                "main_profile_id": profile["id"],
                "agents": [
                    {
                        "id": name,
                        "name": name,
                        "responsibility": "Implement independent module",
                        "model_profile_id": profile["id"],
                        "owned_paths": [f"{name}.txt"],
                    }
                    for name in ("alpha", "beta")
                ],
            },
        ).json()
        assert (
            client.post(
                f"/api/projects/{project['id']}/team/approve",
                json={"conversation_id": conv["id"], "version": team["version"]},
            ).status_code
            == 200
        )
        response = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={
                "content": "Execute the approved plan",
                "access_mode": "commands",
                "execute_team_now": True,
                "team_version": team["version"],
            },
        )
        assert response.status_code == 200 and "event: error" not in response.text
        root = Path(project["repository"])
        assert worker_starts == {"alpha", "beta"}
        assert all((root / name).is_file() for name in ("lead.txt", "alpha.txt", "beta.txt"))
        assert (
            len(lead_calls) == 3
        )  # approved workers, lead write, draft, integration; no polling model loop
        assert any("后台子代理执行状态" in str(m.get("content")) for m in lead_calls[-1])


def test_parallel_latency_baseline(tmp_path):
    """Measure scheduler overhead against identical serial work (not real model throughput)."""

    async def run():
        async def execute(name, *args, **kwargs):
            await asyncio.sleep(0.08)
            return {"status": "completed", "subagent_name": name}

        async def emit(*args):
            pass

        manager = SupervisorManager(tmp_path, "benchmark", max_concurrency=3)
        manager._execute_subagent_task = execute
        kwargs = {"emit_event": emit, "cancel_event": asyncio.Event()}
        start = time.perf_counter()
        for name in ("a", "b", "c"):
            await manager.execute_subagent_task(name, "work", **kwargs)
        serial = time.perf_counter() - start
        start = time.perf_counter()
        manager.start_subagents(
            [{"subagent_name": name, "prompt": "work"} for name in ("a", "b", "c")], **kwargs
        )
        while manager.background_tasks:
            await manager.wait_subagents(1)
        parallel = time.perf_counter() - start
        assert parallel < serial * 0.75, (serial, parallel)

    asyncio.run(run())


def test_worker_reuses_model_configuration_between_tool_steps(tmp_path):
    async def run():
        loaded = []
        manager = SupervisorManager(tmp_path, "cached-model")
        manager.create_subagent("worker", "analysis", "Analyze", model="custom")

        def load(profile_id):
            loaded.append(profile_id)
            return config()

        class Client:
            def stream(self, *args, **kwargs):
                if kwargs["json"]["messages"][-1]["role"] == "tool":
                    return Response({"content": "Completed [r1 run_command]"})
                return Response({"tool_calls": [call("run_command", {"command": "test"})]})

        async def execute(*args):
            return json.dumps({"exit_code": 0, "stdout": "passed"})

        async def emit(*args):
            pass

        manager.tool_executor = execute
        result = await manager.execute_subagent_task(
            "worker",
            "Explain recursion",
            client=Client(),
            default_config=config(),
            load_model_config=load,
            sub_tools=CHAT_TOOLS,
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
        )
        assert result["status"] == "completed" and loaded == ["custom"]
        assert result["phase_timings"]["model_requests"] == 2
        assert result["phase_timings"]["tool_seconds"] >= 0

    asyncio.run(run())
