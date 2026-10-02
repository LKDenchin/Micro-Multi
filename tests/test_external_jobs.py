import asyncio
import json

from masp.external_jobs import ExternalJobs, select_external_tools


def fixture():
    server = {"id": "design", "name": "OpenDesign"}
    lookup = {
        "launch": (server, "start_run"),
        "cancel": (server, "cancel_run"),
        "poll": (server, "get_run"),
    }
    schemas = [
        {
            "function": {
                "name": alias,
                "parameters": {
                    "properties": {"agent": {"type": "string"}} if alias == "launch" else {}
                },
            }
        }
        for alias in lookup
    ]
    return server, lookup, schemas


def test_external_agent_is_opt_in_but_regular_plugins_are_available():
    server, lookup, schemas = fixture()
    regular = {"id": "search", "name": "Search"}
    lookup["search"] = (regular, "search")
    schemas.append({"function": {"name": "search", "parameters": {}}})
    selected, aliases = select_external_tools(schemas, lookup, "制作一个本地动画")
    assert list(aliases) == ["search"]
    assert len(selected) == 1
    assert len(select_external_tools(schemas, lookup, "使用 OpenDesign 制作动画")[0]) == 4


def test_cleanup_only_owns_launched_jobs_and_drops_terminal_jobs():
    async def run():
        server, lookup, _ = fixture()
        jobs = ExternalJobs(lookup)
        jobs.observe(
            server, "get_run", '{"runId":"unrelated"}', '{"id":"unrelated","status":"running"}'
        )
        jobs.observe(server, "start_run", "{}", '{"id":"finished","status":"running"}')
        jobs.observe(server, "get_run", '{"runId":"finished"}', '{"status":"succeeded"}')
        jobs.observe(server, "start_run", "{}", '{"id":"owned","status":"running"}')
        called = []

        async def invoke(provider, name, arguments):
            called.append((provider["id"], name, json.loads(arguments)))
            return '{"status":"canceled"}'

        assert await jobs.close(invoke) == [{"id": "owned", "status": "cancel_requested"}]
        assert called == [("design", "cancel_run", {"runId": "owned"})]
        assert not jobs.jobs

    asyncio.run(run())


def test_cleanup_failure_is_reported():
    async def run():
        server, lookup, _ = fixture()
        jobs = ExternalJobs(lookup)
        jobs.observe(server, "start_run", "{}", '{"id":"owned","status":"running"}')

        async def invoke(*args):
            return "MCP tool error: denied"

        result = await jobs.close(invoke)
        assert result[0]["status"] == "cleanup_failed"

    asyncio.run(run())


def test_chat_final_cleans_its_unfinished_external_job(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from test_autonomous_collaboration import call
    from test_model_recovery import FinishedResponse

    from masp.api import create_app

    server, lookup, schemas = fixture()
    invoked = []

    async def discover(*args, **kwargs):
        return schemas, lookup

    async def mcp(provider, name, arguments, root):
        invoked.append((name, json.loads(arguments)))
        return (
            '{"id":"owned","status":"running"}' if name == "start_run" else '{"status":"canceled"}'
        )

    count = 0

    def stream(self, *args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return FinishedResponse(
                {"tool_calls": [call("launch", {"agent": "fixture"})]}, "tool_calls"
            )
        return FinishedResponse({"content": "结果尚未完成。"}, "stop")

    async def offline(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("masp.api.discover_tools", discover)
    monkeypatch.setattr("masp.api.call_mcp_tool", mcp)
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", offline)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "fixture", "model": "fixture", "base_url": "http://localhost:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
        response = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={
                "content": "使用OpenDesign创建设计",
                "main_only": True,
                "access_mode": "commands",
            },
        )
        assert response.status_code == 200
        assert invoked == [("start_run", {"agent": "fixture"}), ("cancel_run", {"runId": "owned"})]
        assert "unfinished_external_jobs" in response.text
        message = next(
            m
            for m in client.get(f"/api/conversations/{conv['id']}/messages").json()
            if m["role"] == "assistant"
        )
        assert any(event["name"] == "external_job_cleanup" for event in message["tool_events"])
