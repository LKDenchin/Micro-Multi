"""Real extension lifecycle, skill resources and MCP protocol regressions."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_autonomous_collaboration import Response

from masp.api import create_app
from masp.mcp_bridge import _parameters, call_tool, discover_tools, probe_server
from masp.plugin_tools import (
    discover_plugins,
    execute_plugin,
    install_dsh_plugin_from_path,
    manage_extension,
    remove_extension_bundle,
    set_extension_enabled,
)
from masp.skills import list_skills, load_skill, read_skill_resource
from masp.storage import Store


def bundle_source(tmp_path):
    root = tmp_path / "extension-source"
    root.mkdir()
    (root / "echo.py").write_text(
        "import json,sys,os;print(json.dumps({'value':json.load(sys.stdin)['value'],'cwd':os.getcwd(),'workspace':os.environ['MICRO_MULTI_WORKSPACE']}))"
    )
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "working-extension",
                "tools": [
                    {
                        "name": "echo",
                        "command": sys.executable,
                        "args": ["echo.py"],
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                        },
                    }
                ],
            }
        )
    )
    skill = root / "skills" / "helper"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: helper\ndescription: Test resources\n---\nRead references/check.md."
    )
    (skill / "references" / "check.md").write_text("Run meaningful checks.")
    (root / "extension_server.py").write_text(
        "from mcp.server import MCPServer\nimport os\ns=MCPServer('env')\n@s.tool()\ndef environment()->str:\n return os.environ['EXTENSION_VALUE']+'|'+os.getcwd()\ns.run(transport='stdio')\n"
    )
    (root / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "environment": {
                        "command": sys.executable,
                        "args": ["extension_server.py"],
                        "env": {"EXTENSION_VALUE": "retained"},
                        "enabled": True,
                    }
                }
            }
        )
    )
    return root


def test_bundle_real_tools_skills_mcp_and_lifecycle(tmp_path):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    root = bundle_source(tmp_path)
    bundle = install_dsh_plugin_from_path(store, home, str(root))
    schemas, mapping = discover_plugins(store)
    assert len(schemas) == 1
    plugin = next(iter(mapping.values()))
    result = json.loads(execute_plugin(plugin, '{"value":"working"}', tmp_path, store))
    assert result["value"] == "working" and Path(result["cwd"]) == root
    assert Path(result["workspace"]) == tmp_path
    assert "helper" in {item["name"] for item in list_skills(None, home)}
    assert "references/check.md" in load_skill(None, home, "helper")
    assert (
        read_skill_resource(None, home, "helper", "references/check.md") == "Run meaningful checks."
    )
    server = store.list("mcp_server")[0]
    assert server["env"]["EXTENSION_VALUE"] == "retained" and Path(server["cwd"]) == root
    assert "retained" in asyncio.run(call_tool(server, "environment", "{}", tmp_path))
    # Reinstallation updates owned IDs without accumulating duplicate components.
    install_dsh_plugin_from_path(store, home, str(root))
    assert len(store.list("plugin")) == len(store.list("mcp_server")) == 1
    set_extension_enabled(store, bundle["id"], False)
    assert discover_plugins(store)[0] == [] and list_skills(None, home) == []
    assert asyncio.run(discover_tools(store, tmp_path))[0] == []
    with pytest.raises(ValueError):
        execute_plugin(plugin, "{}", tmp_path, store)
    with pytest.raises(ValueError):
        load_skill(None, home, "helper")
    set_extension_enabled(store, bundle["id"], True)
    assert discover_plugins(store)[0] and list_skills(None, home)
    remove_extension_bundle(store, bundle["id"])
    assert store.list("plugin") == store.list("mcp_server") == []
    assert list_skills(None, home) == []


def test_native_cordis_and_invalid_schema_do_not_claim_installed(tmp_path):
    store = Store(tmp_path / "home" / "store.sqlite3")
    root = tmp_path / "native"
    root.mkdir()
    (root / "package.json").write_text('{"name":"native-cordis","main":"index.js"}')
    with pytest.raises(ValueError, match="Cordis"):
        install_dsh_plugin_from_path(store, tmp_path / "home", str(root))
    assert not store.list("dsh_bundle")
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "broken",
                "tools": [
                    {"name": "bad", "command": sys.executable, "parameters": {"type": "nonsense"}}
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="schema"):
        install_dsh_plugin_from_path(store, tmp_path / "home", str(root))
    assert store.list("plugin") == []


def test_plugin_relative_source_and_manager_action_aliases(tmp_path):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    root = bundle_source(tmp_path)
    loaded = manage_extension(
        store,
        home,
        tmp_path,
        "plugin_manager",
        json.dumps({"action": "install_bundle", "target": root.name}),
    )
    bundle_id = loaded["installed"]["id"]
    manage_extension(
        store,
        home,
        tmp_path,
        "plugin_manager",
        json.dumps({"action": "set_bundle", "target": bundle_id, "enabled": False}),
    )
    assert not discover_plugins(store)[0]
    with pytest.raises(ValueError):
        manage_extension(store, home, tmp_path, "load_plugin", "[]")


def test_skill_resource_path_escape_is_rejected(tmp_path):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    install_dsh_plugin_from_path(store, home, str(bundle_source(tmp_path)))
    with pytest.raises((ValueError, FileNotFoundError)):
        read_skill_resource(None, home, "helper", "../../escape.txt")


def test_project_mcp_is_discovered_without_builtin_toggle(tmp_path):
    store = Store(tmp_path / "store.sqlite3")
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "echo": {
                        "command": sys.executable,
                        "args": [str(Path(__file__).with_name("mcp_echo_server.py"))],
                    }
                }
            }
        )
    )
    schemas, mapping = asyncio.run(discover_tools(store, tmp_path, include_builtin=False))
    assert schemas and all("builtin" not in item["function"]["name"] for item in schemas)
    server, tool = next(iter(mapping.values()))
    assert "works" in asyncio.run(call_tool(server, tool, '{"value":"works"}', tmp_path))


def test_mcp_discovery_parallel_and_failure_visible(tmp_path, monkeypatch):
    store = Store(tmp_path / "store.sqlite3")
    for index in range(3):
        store.put("mcp_server", {"id": str(index), "name": str(index), "enabled": True})

    async def run():
        entered = set()
        all_entered = asyncio.Event()

        async def probe(server, cwd):
            entered.add(server["id"])
            if len(entered) == 3:
                all_entered.set()
            await asyncio.wait_for(all_entered.wait(), 0.5)
            if server["id"] == "2":
                raise RuntimeError("unreachable fixture")
            return [{"name": "echo", "description": "echo", "input_schema": {"type": "object"}}]

        monkeypatch.setattr("masp.mcp_bridge.probe_server", probe)
        schemas, _ = await discover_tools(store, tmp_path)
        assert len(schemas) == 2
        assert store.get("mcp_server", "2")["connection_status"] == "failed"
        assert "unreachable fixture" in store.get("mcp_server", "2")["last_error"]

    asyncio.run(run())


def test_mcp_pagination_and_environment_scrubbing(tmp_path, monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def list_tools(self, cursor=None):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="second" if cursor else "first", description="", input_schema={}
                    )
                ],
                next_cursor=None if cursor else "next",
            )

    monkeypatch.setattr("masp.mcp_bridge.Client", Client)
    assert [
        item["name"] for item in asyncio.run(probe_server({"command": "python"}, tmp_path))
    ] == ["first", "second"]
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-inherit")
    params = _parameters({"command": "python", "env": {"EXPLICIT_SECRET": "allowed"}}, tmp_path)
    assert "OPENAI_API_KEY" not in params.env and params.env["EXPLICIT_SECRET"] == "allowed"


def test_unbound_chat_continues_without_project_and_temp_agents(tmp_path, monkeypatch):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)
    requests = []

    def stream(self, *args, **kwargs):
        requests.append(json.loads(json.dumps(kwargs["json"])))
        return Response({"content": "继续原对话"})

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)

    async def no_title(*a, **kw):
        raise RuntimeError("offline")

    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "mock", "model": "mock", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        project = client.post("/api/projects", json={"name": "other"}).json()
        conv = client.post(
            "/api/conversations", json={"title": "unbound", "model_profile_id": profile["id"]}
        ).json()
        for prompt in ("你好", "继续"):
            result = client.post(
                "/api/conversations/" + conv["id"] + "/messages",
                json={"content": prompt, "project_id": None, "access_mode": "commands"},
            )
            assert result.status_code == 200 and "event: complete" in result.text
        stored = client.app.state.service.store.get("conversation", conv["id"])
        assert stored["project_id"] is None
        assert "create_subagent" in {tool["function"]["name"] for tool in requests[-1]["tools"]}
        result = client.post(
            "/api/conversations/" + conv["id"] + "/messages",
            json={"content": "继续", "project_id": project["id"]},
        )
        assert result.status_code == 409


def test_real_http_mcp_headers_and_call(tmp_path):
    import socket
    import threading
    import time

    import uvicorn
    from mcp.server import MCPServer
    from starlette.responses import JSONResponse

    server = MCPServer("HTTP fixture")

    @server.tool()
    def echo(value: str) -> str:
        return value

    accepted = []
    app = server.streamable_http_app(stateless_http=True, json_response=True)

    class HeaderGuard:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                headers = dict(scope["headers"])
                if headers.get(b"authorization") != b"Bearer local-fixture":
                    await JSONResponse({"error": "unauthorized"}, status_code=403)(
                        scope, receive, send
                    )
                    return
                accepted.append(scope["path"])
            await self.app(scope, receive, send)

    app.add_middleware(HeaderGuard)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    http_server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=lambda: http_server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if http_server.started:
                break
            time.sleep(0.03)
        assert http_server.started
        spec = {
            "transport": "http",
            "url": f"http://127.0.0.1:{port}/mcp",
            "headers": {"Authorization": "Bearer local-fixture"},
        }
        assert any(tool["name"] == "echo" for tool in asyncio.run(probe_server(spec, tmp_path)))
        assert "http works" in asyncio.run(
            call_tool(spec, "echo", '{"value":"http works"}', tmp_path)
        )
        assert accepted
    finally:
        http_server.should_exit = True
        thread.join(5)
        sock.close()


def test_chat_load_plugin_then_calls_new_tool_and_survives_rejection(tmp_path, monkeypatch):
    from test_autonomous_collaboration import call

    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)
    source = tmp_path / "local-plugin"
    source.mkdir()
    (source / "echo.py").write_text("import json,sys;print(json.load(sys.stdin)['value'])")
    (source / "tool.json").write_text(
        json.dumps(
            {
                "name": "loaded_echo",
                "command": sys.executable,
                "args": ["echo.py"],
                "parameters": {"type": "object", "properties": {"value": {"type": "string"}}},
            }
        )
    )
    requests = []

    def stream(self, *args, **kwargs):
        payload = kwargs["json"]
        requests.append(payload)
        tools = {item["function"]["name"] for item in payload["tools"]}
        last = payload["messages"][-1]
        if last["role"] != "tool":
            return Response(
                {"tool_calls": [call("load_plugin", {"path": str(source / "tool.json")})]}
            )
        if "installed" in last.get("content", "") or '"status": "failed"' in last.get(
            "content", ""
        ):
            loaded = [name for name in tools if name.startswith("plugin_plugin_")]
            if loaded and "installed" in last.get("content", ""):
                return Response({"tool_calls": [call(loaded[0], {"value": "actually executed"})]})
            return Response({"content": "Unsupported plugin rejected safely"})
        return Response({"content": "Plugin executed successfully"})

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)

    async def no_title(*a, **kw):
        raise RuntimeError("offline")

    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "mock", "model": "mock", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
        result = client.post(
            "/api/conversations/" + conv["id"] + "/messages",
            json={"content": "Load plugin", "access_mode": "commands", "main_only": True},
        )
        assert result.status_code == 200 and "event: complete" in result.text
        assert "actually executed" in result.text, result.text
        assert "Plugin executed successfully" in result.text
        source.joinpath("tool.json").write_text('{"name":"unsupported","cordis":"native"}')
        result = client.post(
            "/api/conversations/" + conv["id"] + "/messages",
            json={"content": "Load invalid plugin", "access_mode": "commands", "main_only": True},
        )
        assert result.status_code == 200 and "event: complete" in result.text
        assert "Unsupported plugin rejected safely" in result.text


def test_worker_refreshes_extension_tools_after_install(tmp_path):
    from test_autonomous_collaboration import call, config

    from masp.supervisor import SupervisorManager

    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    root = bundle_source(tmp_path)

    class Client:
        def stream(self, *a, **kw):
            messages = kw["json"]["messages"]
            names = {tool["function"]["name"] for tool in kw["json"]["tools"]}
            if messages[-1]["role"] != "tool":
                return Response({"tool_calls": [call("load_plugin", {"path": str(root)})]})
            if "installed" in messages[-1].get("content", ""):
                alias = next(name for name in names if name.startswith("plugin_plugin_"))
                return Response({"tool_calls": [call(alias, {"value": "worker executed"})]})
            return Response({"content": "Worker complete"})

    async def run():
        async def execute(name, args, *a):
            if name == "load_plugin":
                return json.dumps(manage_extension(store, home, tmp_path, name, args))
            return await asyncio.to_thread(
                execute_plugin, discover_plugins(store)[1][name], args, tmp_path, store
            )

        async def emit(*a):
            pass

        def tools():
            return [CHAT_TOOLS_ITEM, *discover_plugins(store)[0]]

        manager = SupervisorManager(
            tmp_path, "worker-refresh", tool_executor=execute, refresh_tools=tools
        )
        result = await manager.execute_subagent_task(
            "worker",
            "Load and run extension",
            client=Client(),
            default_config=config(),
            load_model_config=lambda _: config(),
            sub_tools=tools(),
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
            max_turns=4,
        )
        assert result["status"] == "completed" and result["tool_call_count"] == 2

    from masp.chat_tools import CHAT_TOOLS

    CHAT_TOOLS_ITEM = next(tool for tool in CHAT_TOOLS if tool["function"]["name"] == "load_plugin")
    asyncio.run(run())


def test_large_skill_bundle_installs_all_139_skills(tmp_path):
    root = tmp_path / "large-skills"
    for index in range(139):
        directory = root / "skills" / f"skill-{index}"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: skill-{index}\ndescription: Skill {index}\n---\nInstructions",
            encoding="utf-8",
        )
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    bundle = install_dsh_plugin_from_path(store, home, str(root))
    assert len(bundle["skill_names"]) == 139
    assert len(list_skills(None, home)) == 139


def test_plugin_inventory_is_paged_without_large_configuration(tmp_path):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    for index in range(40):
        store.put(
            "mcp_server",
            {
                "id": f"mcp-{index}",
                "name": f"mcp-{index}",
                "enabled": True,
                "env": {"TOKEN": "private"},
                "args": ["x" * 10000],
            },
        )
    result = manage_extension(
        store, home, tmp_path, "plugin_manager", '{"action":"list", "limit":10}'
    )
    assert len(result["inventory"]["mcp_servers"]) == 10
    assert result["counts"]["mcp_servers"] == 41
    assert result["next_offsets"]["mcp_servers"] == 10
    assert "TOKEN" not in json.dumps(result)
    assert len(json.dumps(result)) < 12000


def test_marketplace_loads_large_skill_and_nested_mcp(tmp_path):
    root = tmp_path / "marketplace"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"source": "./plugins/core"}]})
    )
    nested = root / "plugins" / "core"
    nested.mkdir(parents=True)
    (nested / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"nested": {"command": sys.executable, "args": []}}})
    )
    skill = root / "skills" / "8-bit-design"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: 8-bit-design\ndescription: A real large skill\n---\n" + "instruction\n" * 8000
    )
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    bundle = install_dsh_plugin_from_path(store, home, str(root))
    assert bundle["skill_names"] == ["8-bit-design"]
    assert len(load_skill(None, home, "8-bit-design")) > 64000
    assert Path(store.list("mcp_server")[0]["cwd"]) == nested.resolve()
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"source": "./../../outside"}]})
    )
    with pytest.raises(ValueError, match="escapes"):
        install_dsh_plugin_from_path(store, home, str(root))
    assert store.get("dsh_bundle", bundle["id"])["enabled"]


def test_missing_mcp_command_reports_dependency_before_spawn(tmp_path):
    with pytest.raises(FileNotFoundError, match="registering a plugin does not install"):
        _parameters({"command": "micro-multi-nonexistent-cli-12345"}, tmp_path)
