import json

import pytest

from masp.cordis_runtime import close_native_hosts
from masp.native_profiles import list_profiles, save_profile
from masp.plugin_tools import discover_plugins, execute_plugin, set_extension_enabled
from masp.storage import Store


def test_official_loader_config_patch_and_rollback(tmp_path):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    plugin = tmp_path / "configured.mjs"
    plugin.write_text("""import {defineTool} from '@deepseek-ai/dsh-tools';
export const name='profile-fixture';export const inject=['tools'];
export function apply(ctx,config){ctx.tools.register(defineTool({name:'profile_value',description:'Native profile fixture',parameters:{},output:{schema:{type:'object',additionalProperties:false,properties:{value:{type:'string'}}},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},execute:()=>({value:config.value})}));}
""")
    config = json.dumps([{"id": "fixture", "name": plugin.as_uri(), "config": {"value": "base"}}])
    patch = json.dumps([{"id": "fixture", "config": {"value": "patched"}}])
    try:
        saved = save_profile(store, home, "test", config, patch)
        assert saved["active"] and saved["tool_count"] == 1
        native = next(iter(discover_plugins(store)[1].values()))
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        assert json.loads(execute_plugin(native, "{}", workspace, store)) == {"value": "patched"}
        set_extension_enabled(store, "native-profile-test", False)
        assert list_profiles(store, home)["active"] is None and discover_plugins(store)[0] == []
        set_extension_enabled(store, "native-profile-test", True)
        assert json.loads(execute_plugin(native, "{}", workspace, store)) == {"value": "patched"}
        previous = list_profiles(store, home)
        with pytest.raises((ValueError, RuntimeError)):
            save_profile(store, home, "test", "[ invalid yaml", "[]")
        assert list_profiles(store, home) == previous
        assert json.loads(execute_plugin(native, "{}", workspace, store)) == {"value": "patched"}
    finally:
        close_native_hosts(store)


def test_profile_paths_cannot_escape_application_home(tmp_path):
    store = Store(tmp_path / "store.sqlite3")
    with pytest.raises(ValueError, match="Profile name"):
        save_profile(store, tmp_path, "../escape", "[]", "[]")
    assert not (tmp_path.parent / "escape").exists()


def test_native_llm_agents_and_spawn_fork_execute_real_http(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    requests = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [
                {
                    "id": "fixture",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": "native complete"},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "fixture",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                },
            ]
            self.wfile.write(
                (
                    "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                    + "data: [DONE]\n\n"
                ).encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    directory = home / "native-profiles" / "agents"
    directory.mkdir(parents=True)
    (directory / ".env").write_text("FIXTURE_API_KEY=fixture-key\n")
    plugin = tmp_path / "agent-probe.mjs"
    plugin.write_text("""import {defineTool} from '@deepseek-ai/dsh-tools';
import {createUserMessage} from '@deepseek-ai/dsh-llm';
export const name='agent-probe';export const inject=['tools','agents','subagents','microMulti'];
export function apply(ctx){ctx.tools.register(defineTool({name:'native_agent_probe',description:'Real agent lifecycle probe',parameters:{},output:{schema:{type:'object',additionalProperties:true,properties:{}},render:(_a,v)=>[{type:'text',text:JSON.stringify(v)}]},async execute(){
 const handle=await ctx.agents.create({sessionId:'native-model-parent',meta:{cwd:ctx.microMulti.workspace},agentOptions:{provider:'fixture-route',model:'fixture-model'}});
 try{
  handle.agent.followup(createUserMessage({content:[{type:'text',text:'Parent probe'}],source:{kind:'user'}}));await handle.agent.whenIdle();
  const results=[];
  for(const provider of ['spawn','fork']){
   const run=await ctx.subagents.start(provider,{parent:handle.agent,prompt:[{type:'text',text:'Child probe'}],signal:AbortSignal.timeout(10000)});
   try{results.push(await run.result);}finally{await run.dispose();}
  }
  return {results,parentStatus:handle.agent.status};
 }finally{await handle.dispose();}
}}));}
""")
    config = json.dumps(
        [
            {
                "id": "llm",
                "name": "@deepseek-ai/dsh-llm-pi-ai",
                "config": {
                    "providers": {
                        "fixture-route": {
                            "api": "openai-completions",
                            "baseURL": f"http://127.0.0.1:{server.server_port}/v1",
                            "apiKeyEnv": "FIXTURE_API_KEY",
                            "models": [
                                {"id": "fixture-model", "contextWindow": 65536, "maxTokens": 512}
                            ],
                        }
                    }
                },
            },
            {"id": "agent-probe", "name": plugin.as_uri()},
        ]
    )
    try:
        save_profile(store, home, "agents", config, "[]")
        native = next(iter(discover_plugins(store)[1].values()))
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = json.loads(execute_plugin(native, "{}", workspace, store))
        assert result["parentStatus"] == "idle"
        assert [item["stopReason"] for item in result["results"]] == ["completed", "completed"]
        assert all(item["output"][0]["text"] == "native complete" for item in result["results"])
        assert len(requests) == 3 and all(
            request["model"] == "fixture-model" for request in requests
        )
    finally:
        close_native_hosts(store)
        server.shutdown()
        server.server_close()
        thread.join()
