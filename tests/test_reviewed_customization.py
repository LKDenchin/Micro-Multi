import asyncio
import json

from fastapi.testclient import TestClient
from test_autonomous_collaboration import Response, call

from masp.api import create_app
from masp.supervisor import SupervisorManager
from masp.team_review import planning_tool_allowed


def test_pending_team_cannot_launch_and_keeps_complete_tasks(tmp_path):
    manager = SupervisorManager(tmp_path, "review", initial_team={"version": 3})
    manager.require_team_approval = True
    tasks = [
        {
            "subagent_name": "worker",
            "prompt": "Implement the approved module",
            "owned_paths": ["module.py"],
        }
    ]
    result = manager.start_subagents(tasks)
    assert result["status"] == "awaiting_approval"
    assert manager.background_tasks == {}
    assert manager.get_team_event_data()["status"] == "draft"
    assert manager.team_obj["pending_tasks"] == tasks
    assert len(manager.team_obj["plan_documents"]) == 3
    assert all((tmp_path / path).is_file() for path in manager.team_obj["plan_documents"])
    assert (
        json.loads((tmp_path / ".masp/team-plans/review-v3.json").read_text(encoding="utf-8"))[
            "pending_tasks"
        ]
        == tasks
    )


def test_remove_running_child_waits_for_cancellation(tmp_path):
    async def run():
        manager = SupervisorManager(tmp_path, "remove")
        manager.create_subagent("worker", "worker", "work")
        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def child():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        manager.background_tasks["worker"] = asyncio.create_task(child())
        await started.wait()
        await manager.remove_subagent("worker")
        assert cleaned.is_set()
        assert "worker" not in manager.subagents
        assert not manager.background_tasks

    asyncio.run(run())


def test_planning_boundary_only_allows_documents():
    assert planning_tool_allowed("write_file", '{"path":"docs/design.md"}')
    assert not planning_tool_allowed("write_file", '{"path":"src/app.py"}')
    assert not planning_tool_allowed("run_command", '{"command":"npm install"}')
    assert not planning_tool_allowed("external_plugin", "{}")


def test_conversation_edits_and_external_path_stay_in_workspace(tmp_path):
    with TestClient(create_app(tmp_path / "home")) as client:
        project = client.post("/api/projects", json={"name": "Review"}).json()
        conversation = client.post("/api/conversations", json={"project_id": project["id"]}).json()
        changed = client.patch(
            "/api/conversations/" + conversation["id"], json={"title": "Renamed", "pinned": True}
        )
        assert changed.status_code == 200
        assert changed.json()["title"] == "Renamed" and changed.json()["pinned"]
        assert (
            client.get(
                "/api/projects/" + project["id"] + "/workspace/external-path",
                params={"path": "../outside"},
            ).status_code
            == 400
        )


def test_each_turn_submits_new_plan_and_never_starts_unapproved_child(tmp_path, monkeypatch):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    requests = []

    def stream(self, *args, **kwargs):
        requests.append(kwargs["json"])
        if kwargs["json"].get("tool_choice") == "none":
            return Response({"content": "请审核本轮团队方案。"})
        return Response(
            {
                "tool_calls": [
                    call(
                        "start_subagents",
                        {
                            "tasks": [
                                {
                                    "subagent_name": "worker",
                                    "prompt": "Implement this round",
                                    "owned_paths": ["module.py"],
                                }
                            ]
                        },
                    )
                ]
            }
        )

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unapproved child started")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr(SupervisorManager, "_execute_subagent_task", forbidden)
    with TestClient(create_app(tmp_path / "home")) as client:
        client.put("/api/dsh/settings", json={"agentLoop": {"maxToolSteps": 5}})
        profile = client.post(
            "/api/model-profiles",
            json={"name": "Test", "model": "fixture", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        project = client.post("/api/projects", json={"name": "Review"}).json()
        conv = client.post(
            "/api/conversations",
            json={"project_id": project["id"], "model_profile_id": profile["id"]},
        ).json()
        versions = []
        for content in ["实现模块", "修复模块中的问题"]:
            response = client.post(
                "/api/conversations/" + conv["id"] + "/messages", json={"content": content}
            )
            assert response.status_code == 200 and "event: error" not in response.text
            assert "awaiting_approval" in response.text
            team = client.get(
                "/api/projects/" + project["id"] + "/team", params={"conversation_id": conv["id"]}
            ).json()
            assert team["status"] == "draft"
            versions.append(team["version"])
        assert versions[1] > versions[0]
