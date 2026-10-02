"""Enabled MCP servers expose callable tools to the main agent."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from mcp.types import TextContent

from masp.api import create_app
from masp.mcp_bridge import _parameters, call_tool, discover_tools, probe_server
from masp.storage import Store


class FakeClient:
    def __init__(self, parameters, **kwargs):
        self.parameters = parameters

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="lookup",
                    description="Find a record",
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                )
            ]
        )

    async def call_tool(self, name, arguments):
        return SimpleNamespace(
            content=[TextContent(type="text", text=arguments["query"])],
            structured_content=None,
            is_error=False,
        )


def test_mcp_discovery_and_invocation(tmp_path, monkeypatch):
    monkeypatch.setattr("masp.mcp_bridge.Client", FakeClient)
    store = Store(tmp_path / "store.sqlite3")
    server = {
        "id": "mcp-test",
        "name": "Test server",
        "command": "python",
        "args": ["server.py"],
        "enabled": True,
    }
    store.put("mcp_server", server)
    assert asyncio.run(probe_server(server, tmp_path))[0]["name"] == "lookup"
    schemas, mapping = asyncio.run(discover_tools(store, tmp_path))
    alias = schemas[0]["function"]["name"]
    assert alias.startswith("mcp_")
    assert mapping[alias][1] == "lookup"
    assert asyncio.run(call_tool(server, "lookup", json.dumps({"query": "hello"}), tmp_path)) == (
        "hello"
    )


def test_real_stdio_server(tmp_path):
    server = {
        "command": sys.executable,
        "args": [str(Path(__file__).with_name("mcp_echo_server.py"))],
    }
    tools = asyncio.run(probe_server(server, tmp_path))
    assert any(item["name"] == "echo" for item in tools)
    result = asyncio.run(call_tool(server, "echo", '{"value":"connected"}', tmp_path))
    assert "connected" in result


def test_mcp_server_management_api(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "masp.api.probe_server",
        lambda server, cwd: asyncio.sleep(
            0, result=[{"name": "lookup", "description": "", "input_schema": {}}]
        ),
    )
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        response = client.post(
            "/api/mcp-servers",
            json={"name": "Local", "command": "python", "args": ["server.py"]},
        )
        assert response.status_code == 201
        server = response.json()
        assert not server["enabled"]
        assert (
            client.post(f"/api/mcp-servers/{server['id']}/probe", json={}).json()["tools"][0][
                "name"
            ]
            == "lookup"
        )
        updated = client.put(
            f"/api/mcp-servers/{server['id']}",
            json={"name": "Local", "command": "python", "args": ["server.py"], "enabled": True},
        )
        assert updated.json()["enabled"]
        assert (
            client.request("DELETE", f"/api/mcp-servers/{server['id']}", json={}).status_code == 204
        )
        assert client.get("/api/mcp-servers").json() == []


def test_remote_http_mcp_uses_streamable_http_url(tmp_path):
    url = "https://mcp.example.test/mcp"
    assert _parameters({"transport": "http", "url": url}, tmp_path) == url
    with TestClient(create_app(tmp_path / "home")) as client:
        result = client.post(
            "/api/mcp-servers",
            json={
                "name": "remote",
                "transport": "http",
                "url": url,
            },
        )
        assert result.status_code == 201
        assert result.json()["transport"] == "http"
