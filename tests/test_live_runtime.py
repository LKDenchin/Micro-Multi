"""Live turns and persistent real MCP connections, including disconnects."""

import asyncio
import json
import sys

from fastapi.testclient import TestClient
from test_autonomous_collaboration import Response, call

from masp.api import create_app
from masp.domain import ChatMessageCreate
from masp.mcp_bridge import call_tool, probe_server
from masp.mcp_connections import close_connections
from masp.turn_hub import TurnHub


def test_disconnected_subscriber_does_not_cancel_or_repeat_work():
    async def run():
        hub = TurnHub()
        gate = asyncio.Event()
        executions = []

        async def source():
            yield 'data: {"delta":"first"}\n\n'
            await gate.wait()
            executions.append("write")
            yield 'data: {"delta":"second"}\n\n'
            yield "event: complete\ndata: {}\n\n"

        turn = hub.start("conversation", "message", source())
        subscriber = turn.subscribe()
        assert "first" in await anext(subscriber)
        await subscriber.aclose()
        assert hub.running("conversation")
        gate.set()
        await turn.task
        replay = "".join([frame async for frame in turn.subscribe(after=1)])
        assert "second" in replay and "complete" in replay and executions == ["write"]
        await hub.close()

    asyncio.run(run())


def test_api_disconnect_keeps_file_operation_and_durable_completion(tmp_path, monkeypatch):
    state = {}
    requests = []

    class GatedResponse(Response):
        async def aiter_lines(self):
            await state["gate"].wait()
            async for line in super().aiter_lines():
                yield line

    def provider(self, *args, **kwargs):
        requests.append(kwargs["json"])
        if len(requests) == 1:
            return GatedResponse(
                {
                    "tool_calls": [
                        call("write_file", {"path": "after-disconnect.txt", "content": "done"})
                    ]
                }
            )
        return Response({"content": "Completed once [r1 write_file]"})

    async def offline(*args, **kwargs):
        raise RuntimeError("offline title")

    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)
    monkeypatch.setattr("httpx.AsyncClient.stream", provider)
    monkeypatch.setattr("httpx.AsyncClient.post", offline)
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "test", "model": "test", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", "") == "/api/conversations/{conversation_id}/messages"
        and "POST" in getattr(route, "methods", set())
    )

    async def run():
        state["gate"] = asyncio.Event()
        async with app.router.lifespan_context(app):
            response = await endpoint(
                conv["id"],
                ChatMessageCreate(
                    content="Create the requested file", access_mode="commands", main_only=True
                ),
            )
            subscriber = response.body_iterator
            await anext(subscriber)
            await subscriber.aclose()  # Same generator cancellation as a disconnected SSE client.
            assert app.state.turns.running(conv["id"])
            state["gate"].set()
            turn = app.state.turns.turns[conv["id"]]
            await asyncio.wait_for(turn.task, 20)
            assert (
                tmp_path / "home" / "temporary" / conv["id"] / "after-disconnect.txt"
            ).read_text() == "done"
            saved = app.state.service.store.get("message", turn.message_id)
            assert saved["execution_status"] == "completed" and "Completed once" in saved["content"]
            assert len(requests) == 2

    asyncio.run(run())


def test_real_mcp_connection_keeps_process_state_and_concurrent_calls(tmp_path):
    script = tmp_path / "stateful_server.py"
    script.write_text("""from mcp.server import MCPServer
import os
server=MCPServer("stateful")
count=0
@server.tool()
def increment() -> dict:
    global count
    count+=1
    return {"count":count,"pid":os.getpid()}
if __name__=="__main__":server.run(transport="stdio")
""")
    server = {"id": "stateful", "command": sys.executable, "args": [str(script)]}

    async def run():
        try:
            assert len(await probe_server(server, tmp_path)) == 1
            values = [
                json.loads(await call_tool(server, "increment", "{}", tmp_path)) for _ in range(2)
            ]
            concurrent = await asyncio.gather(
                *(call_tool(server, "increment", "{}", tmp_path) for _ in range(3))
            )
            values.extend(json.loads(item) for item in concurrent)
            assert {item["pid"] for item in values} == {values[0]["pid"]}
            assert sorted(item["count"] for item in values) == [1, 2, 3, 4, 5]
        finally:
            await close_connections()

    asyncio.run(run())
