import asyncio
import json

import pytest

from masp.supervisor import SupervisorManager
from masp.workspace_coordination import WorkspaceCoordinator


def test_cleanup_blocks_creation_and_cancel_releases_lease(tmp_path):
    async def run():
        coordinator = WorkspaceCoordinator(tmp_path)
        entered = asyncio.Event()
        release = asyncio.Event()
        created = asyncio.Event()

        async def cleanup():
            async with coordinator.lease("cleanup", ["test6"]):
                entered.set()
                await release.wait()

        async def create():
            async with coordinator.operation("write_file", '{"path":"test6/index.html"}'):
                created.set()

        task = asyncio.create_task(cleanup())
        await entered.wait()
        writer = asyncio.create_task(create())
        await asyncio.sleep(0.02)
        assert not created.is_set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.wait_for(writer, 1)
        assert not coordinator.active

    asyncio.run(run())


def test_disjoint_scopes_are_parallel_and_cross_scope_delete_is_denied(tmp_path):
    async def run():
        c = WorkspaceCoordinator(tmp_path)
        async with c.lease("first", ["a"]):
            async with c.lease("second", ["b"]):
                assert len(c.active) == 2
                with pytest.raises(PermissionError):
                    async with c.operation("delete_file", '{"path":"a/game.js"}'):
                        pytest.fail("must not delete another scope")
        async with c.lease("author", ["a"]):
            async with c.operation("write_file", '{"path":"a/game.js"}'):
                (tmp_path / "a").mkdir()
                (tmp_path / "a/game.js").write_text("game")
        with pytest.raises(PermissionError):
            async with c.operation("delete_file", '{"path":"a/game.js"}'):
                pytest.fail("must not delete this turn's delivered file")
        assert (tmp_path / "a/game.js").read_text() == "game"

    asyncio.run(run())


def test_dependency_failure_prevents_creator_and_cycle_is_atomic(tmp_path):
    async def run():
        manager = SupervisorManager(tmp_path, "dependencies")
        invoked = []

        async def execute(name, *args, **kwargs):
            invoked.append(name)
            return {"status": "failed", "subagent_name": name}

        async def emit(*args):
            pass

        manager._execute_subagent_task = execute
        with pytest.raises(ValueError, match="Cyclic"):
            manager.start_subagents(
                [
                    {"subagent_name": "a", "prompt": "a", "depends_on": ["b"]},
                    {"subagent_name": "b", "prompt": "b", "depends_on": ["a"]},
                ]
            )
        assert not manager.background_tasks and not manager.subagents
        manager.start_subagents(
            [
                {"subagent_name": "clean", "prompt": "clean"},
                {"subagent_name": "build", "prompt": "build", "depends_on": ["clean"]},
            ],
            emit_event=emit,
            cancel_event=asyncio.Event(),
        )
        reports = []
        while manager.background_tasks:
            reports.extend((await manager.wait_subagents(1))["reports"])
        assert invoked == ["clean"]
        assert len(reports) == 2 and all(r["status"] == "failed" for r in reports)

    asyncio.run(run())


def test_inherited_model_can_replace_explicit_binding(tmp_path):
    manager = SupervisorManager(tmp_path, "models")
    manager.create_subagent("worker", "worker", "task", model="v4")
    manager.adjust_subagent("worker", model="")
    assert manager.subagents["worker"].model_profile_id is None
    manager.create_subagent("worker", "worker", "task", model="v4")
    manager.create_subagent("worker", "worker", "task", model="")
    assert manager.subagents["worker"].model_profile_id is None


def test_inherited_and_explicit_models_and_readonly_refresh(tmp_path):
    from test_autonomous_collaboration import Response, config

    from masp.chat_tools import CHAT_TOOLS

    async def run():
        requested = []
        events = []

        class Client:
            def stream(self, *args, **kwargs):
                requested.append(kwargs["json"])
                return Response({"content": "独立分析成果"})

        async def emit(kind, data):
            events.append((kind, dict(data)))

        main = config()
        main.model = "v3"
        explicit = config()
        explicit.model = "v4"
        manager = SupervisorManager(tmp_path, "routing", refresh_tools=lambda: CHAT_TOOLS)
        kwargs = dict(
            client=Client(),
            default_config=main,
            load_model_config=lambda profile: explicit,
            sub_tools=[t for t in CHAT_TOOLS if t["function"]["name"] == "read_file"],
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
            max_turns=2,
        )
        manager.create_subagent("worker", "worker", "分析")
        for profile in ("", "v4", ""):
            manager.adjust_subagent("worker", model=profile)
            report = await manager.execute_subagent_task("worker", "分析需求", **kwargs)
            assert report["status"] == "completed"
        assert [r["model"] for r in requested] == ["v3", "v4", "v3"]
        assert all(
            {t["function"]["name"] for t in r.get("tools", [])} <= {"read_file"} for r in requested
        )
        assert [data for kind, data in events if kind == "subagent_progress"][-1][
            "effective_model"
        ] == "v3"
        assert report["model_steps"][0]["model"] == "v3"

    asyncio.run(run())


def test_reverse_dependency_admission_and_shell_deletion_are_safe(tmp_path):
    from masp.chat_tools import CHAT_TOOLS

    async def run():
        manager = SupervisorManager(tmp_path, "reverse")
        sequence = []

        async def execute(name, *args, **kwargs):
            sequence.append(name)
            return {"status": "completed", "subagent_name": name}

        async def emit(*args):
            pass

        manager._execute_subagent_task = execute
        manager.start_subagents(
            [
                {"subagent_name": "build", "prompt": "build", "depends_on": ["clean"]},
                {"subagent_name": "clean", "prompt": "clean"},
            ],
            sub_tools=CHAT_TOOLS,
            emit_event=emit,
            cancel_event=asyncio.Event(),
        )
        while manager.background_tasks:
            await asyncio.wait_for(manager.wait_subagents(1), 2)
        assert sequence == ["clean", "build"]
        assert not manager.coordinator.pending and not manager.coordinator.active
        with pytest.raises(PermissionError):
            async with manager.coordinator.operation(
                "run_command", json.dumps({"command": "Remove-Item -Recurse test6"})
            ):
                pytest.fail("destructive shell must not bypass ownership")

    asyncio.run(run())


def test_external_generator_prevents_duplicate_local_creation(tmp_path):
    async def run():
        coordinator = WorkspaceCoordinator(tmp_path)
        coordinator.external_busy = True
        with pytest.raises(PermissionError):
            async with coordinator.operation("write_file", '{"path":"test6/index.html"}'):
                pytest.fail("must not write competing fallback")
        async with coordinator.operation("mcp:cancel_run", '{"runId":"owned"}'):
            pass
        coordinator.external_busy = False
        async with coordinator.operation("write_file", '{"path":"test6/index.html"}'):
            pass

    asyncio.run(run())


def test_selected_main_model_persists_for_next_turn_and_inherited_child(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from test_model_recovery import FinishedResponse

    from masp.api import create_app

    requests = []

    def stream(self, *args, **kwargs):
        requests.append(kwargs["json"]["model"])
        return FinishedResponse({"content": "分析完成"}, "stop")

    async def offline(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", offline)
    with TestClient(create_app(tmp_path / "home")) as client:
        profiles = [
            client.post(
                "/api/model-profiles",
                json={"name": model, "model": model, "base_url": "http://localhost:9999/v1"},
            ).json()
            for model in ("v4", "v3")
        ]
        conv = client.post(
            "/api/conversations", json={"model_profile_id": profiles[0]["id"]}
        ).json()
        url = f"/api/conversations/{conv['id']}"
        response = client.post(
            url + "/messages", json={"content": "分析需求", "model_profile_id": profiles[1]["id"]}
        )
        assert response.status_code == 200
        stored = client.app.state.service.store.get("conversation", conv["id"])
        assert stored["model_profile_id"] == profiles[1]["id"]
        assert stored["team"]["main_profile_id"] == profiles[1]["id"]
        client.post(url + "/messages", json={"content": "继续分析需求"})
        assert requests and set(requests) == {"v3"}
