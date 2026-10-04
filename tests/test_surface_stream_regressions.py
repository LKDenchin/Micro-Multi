"""Exercise collaboration delivery and native plugin seams without UI clicks."""

import asyncio
import base64
import json
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from test_autonomous_collaboration import call
from test_model_recovery import FinishedResponse

from masp.api import create_app
from masp.chat_tools import _safe_file
from masp.compaction import RepeatToolReminder
from masp.cordis_runtime import CordisWorker, native_manifest
from masp.model_runtime import compatible_model_stream, complete_stream_result, model_stream_lines
from masp.model_settings import load_config
from masp.plugin_models import openai_chunk, request_options
from masp.storage import Store
from masp.turn_hub import LiveTurn, coalesce_text_frames
from masp.turn_journal import TurnJournal


@pytest.mark.parametrize(
    "tool", ["start_subagents", "dispatch_subagents_parallel", "dispatch_subagent_task"]
)
def test_plan_delivered_in_first_response_without_analysis_or_extra_model_call(
    tmp_path, monkeypatch, tool
):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    requests = []

    def stream(self, *args, **kwargs):
        requests.append(kwargs["json"])
        assert len(requests) == 1, "A submitted plan must end the planning model loop"
        return FinishedResponse(
            {
                "content": "INTERNAL_ANALYSIS",
                "tool_calls": [
                    call(
                        tool,
                        (
                            {
                                "subagent_name": "builder",
                                "prompt": "Implement the requested feature",
                            }
                            if tool == "dispatch_subagent_task"
                            else {
                                "tasks": [
                                    {
                                        "subagent_name": "builder",
                                        "prompt": "Implement the requested feature",
                                        "owned_paths": ["app.py"],
                                    }
                                ]
                            }
                        ),
                    )
                ],
            },
            "tool_calls",
        )

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "main", "model": "fixture", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
        url = "/api/conversations/" + conv["id"]
        response = client.post(
            url + "/messages",
            json={
                "content": "Implement a feature",
                "access_mode": "commands",
                "review_team_plan": True,
            },
        )
        assert "event: team" in response.text
        assert "pending_tasks" in response.text
        frames = [
            json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")
        ]
        assert any(
            frame.get("kind") == "work" and "INTERNAL_ANALYSIS" in frame.get("content", "")
            for frame in frames
        )
        assert all("INTERNAL_ANALYSIS" not in frame.get("delta", "") for frame in frames)
        assert len(requests) == 1
        saved = next(
            item for item in client.get(url + "/messages").json() if item["role"] == "assistant"
        )
        assert saved["thinking"]["kind"] == "work"
        assert "INTERNAL_ANALYSIS" in saved["thinking"]["content"]
        assert any(item["type"] == "team_plan" for item in saved["segments"])
        assert "INTERNAL_ANALYSIS" not in saved["content"]
        assert saved["execution_status"] == "completed"


def test_plan_documents_readable_without_exposing_internal_records(tmp_path):
    folder = tmp_path / ".masp" / "team-plans" / "conv-v1"
    folder.mkdir(parents=True)
    file = folder / "requirements.md"
    file.write_text("# Requirements", encoding="utf-8")
    assert _safe_file(tmp_path, file.relative_to(tmp_path).as_posix()) == file
    private = tmp_path / ".masp" / "private.md"
    private.write_text("private", encoding="utf-8")
    with pytest.raises(ValueError):
        _safe_file(tmp_path, ".masp/private.md")


def test_model_name_resolves_to_unique_profile_and_keeps_wire_id(tmp_path, monkeypatch):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    store = Store(tmp_path / "db.sqlite3")
    wire = '["provider","model"]'
    profile = {
        "id": "model-profile",
        "name": "Readable model",
        "model": wire,
        "base_url": "http://localhost/v1",
        "has_api_key": False,
        "temperature": 0.2,
        "top_p": 1.0,
        "max_output_tokens": 8192,
        "timeout_seconds": 90,
    }
    store.put("model_profile", profile)
    assert load_config(store, tmp_path, "Readable model").model == wire
    with pytest.raises(ValueError, match="模型配置不可用"):
        load_config(store, tmp_path, "invented")


def test_replay_preserves_order_and_only_returns_new_frames():
    async def exercise():
        turn = LiveTurn("message")
        for index in range(1000):
            turn.publish(f"data: {index}\n\n")
        turn.finished_at = 1
        frames = [frame async for frame in turn.subscribe(998)]
        assert frames == ["id: 999\ndata: 998\n\n", "id: 1000\ndata: 999\n\n"]

    asyncio.run(exercise())


def test_text_batches_commit_once_and_preserve_semantic_boundaries(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    store.put("conversation", {"id": "c"})
    journal = TurnJournal(store, "c", "m", "created", "model")
    writes = []
    put = store.put

    def record_put(*args, **kwargs):
        writes.append(args[0])
        return put(*args, **kwargs)

    store.put = record_put

    async def source():
        yield 'data: {"delta":"first"}\n\n'
        yield 'data: {"delta":"second"}\n\n'
        yield 'event: team\ndata: {"status":"draft"}\n\n'
        yield 'data: {"delta":"third"}\n\n'

    async def exercise():
        frames = [frame async for frame in coalesce_text_frames(source())]
        assert len(frames) == 3
        assert frames[1].startswith("event: team")
        await journal.consume_async(frames[0])
        assert writes == ["message"]
        assert store.get("message", "m")["content"] == "firstsecond"
        store.update(
            "message",
            "m",
            content="final",
            termination_reason=None,
            segments=[{"type": "text", "content": "final"}],
        )
        await journal.consume_async(frames[2])
        assert store.get("message", "m")["content"] == "final"

    asyncio.run(exercise())


def test_turn_timeout_survives_provider_consuming_cancellation():
    async def source():
        yield 'data: {"delta":"saved"}\n\n'
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            yield "event: complete\ndata: {}\n\n"

    async def exercise():
        frames = []
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                async for frame in coalesce_text_frames(source()):
                    frames.append(frame)
        assert any("saved" in frame for frame in frames)
        assert not any("event: complete" in frame for frame in frames)

    asyncio.run(exercise())


def test_native_http_route_preserves_body_query_headers_and_disposes():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    module = (Path(__file__).parents[1] / "src/masp/native/plugin_webserver.mjs").as_uri()
    script = f"""import {{Context}} from '@deepseek-ai/cordis';
import WebServer from {json.dumps(module)};
const ctx=new Context();await ctx.plugin(WebServer,{{}});
const fiber=ctx.plugin({{inject:['webServer'],apply(scope){{scope.webServer.register({{kind:'exact',path:'/fixture/config',handler:async(req,res)=>{{let body='';for await(const part of req)body+=part;res.writeHead(201,{{'content-type':'application/json'}});res.end(JSON.stringify({{body,url:req.url,host:req.headers.host}}));}}}});}}}});await fiber;
const response=await ctx.webServer.request({{path:'/fixture/config?probe=1',method:'POST',headers:{{host:'localhost','content-type':'text/plain'}},body:Buffer.from('payload').toString('base64')}});
console.log(JSON.stringify(response));await fiber.dispose();
const removed=await ctx.webServer.request({{path:'/fixture/config',method:'GET',headers:{{}}}});if(removed.status!==404)throw Error('route leaked');await ctx.fiber.dispose();"""
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout.strip())
    assert response["status"] == 201
    payload = json.loads(base64.b64decode(response["body"]))
    assert payload == {"body": "payload", "url": "/fixture/config?probe=1", "host": "localhost"}


def test_native_http_body_above_tool_protocol_limit(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "http-fixture",
                "type": "module",
                "microMulti": {"cordis": {"entry": "host.mjs"}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "host.mjs").write_text(
        "export const inject=['webServer']; export function apply(ctx){ctx.webServer.register({kind:'exact',path:'/fixture/large',handler:(req,res)=>res.end('x'.repeat(600000))});ctx.webServer.register({kind:'exact',path:'/fixture/config',handler:async(req,res)=>{let size=0;for await(const chunk of req)size+=chunk.length;res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({size,host:req.headers.host}));}});}",
        encoding="utf-8",
    )
    manifest = native_manifest(tmp_path)
    assert manifest is not None
    worker = CordisWorker(tmp_path / "home", manifest, tmp_path)
    try:
        result = worker.request(
            "plugin-http",
            path="/fixture/config",
            method="POST",
            headers={"host": "localhost"},
            body=base64.b64encode(b"x" * 600000).decode(),
        )
        assert result["status"] == 200
        assert json.loads(base64.b64decode(result["body"])) == {"size": 600000, "host": "localhost"}
        large = worker.request("plugin-http", path="/fixture/large", method="GET", headers={})
        assert base64.b64decode(large["body"]) == b"x" * 600000
    finally:
        worker.close()


def test_alternating_edits_reach_loop_cutoff():
    guard = RepeatToolReminder()
    for _ in range(8):
        guard.record("edit_file", {"old": "A", "new": "B"})
        guard.record("edit_file", {"old": "B", "new": "A"})
    assert guard.repeat_count >= 8


def test_clean_eof_requires_complete_tool_arguments():
    assert complete_stream_result("hello", [])
    assert complete_stream_result("", [{"function": {"name": "read_file", "arguments": "{}"}}])
    assert not complete_stream_result(
        "partial", [{"function": {"name": "read_file", "arguments": "{"}}]
    )
    assert not complete_stream_result("", [])


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("stop", "stop"),
        ({"kind": "stop"}, "stop"),
        ({"kind": "tool-calls"}, "tool_calls"),
        ({"kind": "max-tokens"}, "length"),
    ],
)
def test_native_model_finish_reason_preserves_structured_contract(reason, expected):
    assert (
        openai_chunk({"type": "finish", "reason": reason}, {})["choices"][0]["finish_reason"]
        == expected
    )


@pytest.mark.parametrize("sse", [True, False])
def test_model_message_envelope_and_clean_json_response(sse):
    packet = {"choices": [{"message": {"content": "hello", "reasoning": "working"}}]}

    class Response:
        async def aiter_lines(self):
            yield ("data: " if sse else "") + json.dumps(packet)

    async def exercise():
        frames = [line async for line in model_stream_lines(Response(), 2)]
        canonical = json.loads(next(line[5:] for line in frames if line.startswith("data: ")))
        assert canonical["choices"][0]["delta"]["content"] == "hello"

    asyncio.run(exercise())


def test_provider_error_is_not_silently_treated_as_empty_stream():
    class Response:
        async def aiter_lines(self):
            yield 'data: {"error":{"message":"provider rejected request"}}'

    async def exercise():
        with pytest.raises(RuntimeError, match="provider rejected"):
            async for _ in model_stream_lines(Response(), 2):
                pass

    asyncio.run(exercise())


def test_legacy_native_settings_survive_edit_and_host_restart(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "settings-fixture",
                "type": "module",
                "microMulti": {"cordis": {"entry": "host.mjs"}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "host.mjs").write_text(
        "import z from '@deepseek-ai/schemastery'; export const name='fixture-settings'; export const Config=z.object({enabled:z.boolean().default(false)}); export function apply(){}",
        encoding="utf-8",
    )
    manifest = native_manifest(tmp_path)
    assert manifest
    home = tmp_path / "home"

    def remote(worker, method, args):
        result = worker.request(
            "plugin-rpc", channel="/api", method="settings/" + method, payload={"args": args}
        )["result"]
        assert result["ok"], result
        return result.get("value")

    worker = CordisWorker(home, manifest, tmp_path)
    try:
        descriptor = remote(worker, "describe", {})["namespaces"][0]
        remote(
            worker,
            "update",
            {
                "ns": descriptor["ns"],
                "patch": {"enabled": True},
                "expectedRevision": descriptor["revision"],
            },
        )
        assert remote(worker, "describe", {})["namespaces"][0]["value"]["enabled"] is True
    finally:
        worker.close()

    worker = CordisWorker(home, manifest, tmp_path)
    try:
        assert remote(worker, "describe", {})["namespaces"][0]["value"]["enabled"] is True
    finally:
        worker.close()


def test_plugin_model_image_uses_durable_native_attachment(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "image-fixture",
                "type": "module",
                "microMulti": {"cordis": {"entry": "host.mjs"}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "host.mjs").write_text(
        """import {LlmAdapter} from '@deepseek-ai/dsh-llm';
export const inject=['llm','attachments'];export function apply(ctx){
 class Adapter extends LlmAdapter{listModels(provider){return [{provider,id:'image',name:'Image'}];}resolveModel(provider,id){return {provider,id,name:'Image',reasoning:{efforts:[{id:'high',name:'High'}]}};}async *stream(options){const block=options.messages[0].content[0];if(block.type!=='image'||!block.attachment.attachmentId)throw Error('Image was not materialized');const stored=await ctx.attachments.readImage(block.attachment);if(!stored.data.length)throw Error('Empty image');yield {type:'text-delta',index:0,text:'image accepted'};yield {type:'finish',reason:{kind:'stop'}};}}
 ctx.llm.registerAdapter(['fixture'],new Adapter());ctx.root.llm.registerAdapter(['root-fixture'],new Adapter());}
""",
        encoding="utf-8",
    )
    manifest = native_manifest(tmp_path)
    assert manifest

    def png_chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    image = base64.b64encode(
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + png_chunk(b"IEND", b"")
    ).decode()
    options = request_options(
        {
            "model": '["fixture","image"]',
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64," + image},
                        }
                    ],
                }
            ],
        }
    )
    manifest["plugins"][0]["bundleId"] = "image-fixture"
    worker = CordisWorker(tmp_path / "home", manifest, tmp_path)
    try:
        cap = worker.request("plugin-capabilities", pluginId="image-fixture")
        assert cap["providesModels"], cap
        catalog = worker.request("plugin-models", pluginId="image-fixture")
        assert {model["provider"] for model in catalog["models"]} == {"fixture"}
        assert catalog["models"][0]["reasoning"]["efforts"][0]["id"] == "high"
        assert worker.request("plugin-model-stream", options=options, streamId="image")["complete"]
        frames = []
        while not worker.events.empty():
            packet = worker.events.get_nowait()
            if packet.get("event") == "plugin-model-chunk":
                if frame := openai_chunk(packet["chunk"], {}):
                    frames.append(frame)
        assert any(
            frame["choices"][0]["delta"].get("content") == "image accepted" for frame in frames
        )
        assert frames[-1]["choices"][0]["finish_reason"] == "stop"
    finally:
        worker.close()


def test_disconnecting_plugin_stream_does_not_stop_shared_native_host(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "events-fixture",
                "type": "module",
                "microMulti": {"cordis": {"entry": "host.mjs"}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "host.mjs").write_text("export function apply(){}", encoding="utf-8")
    manifest = native_manifest(tmp_path)
    assert manifest
    worker = CordisWorker(tmp_path / "home", manifest, tmp_path)
    monkeypatch.setattr("masp.plugin_surface.surface_host", lambda *args: worker)
    from masp.plugin_surface import rpc_stream

    async def verify():
        ready = anyio.Event()

        async def subscribe():
            source = rpc_stream(
                None,
                tmp_path,
                "fixture",
                {"channel": "/api", "method": "$events", "payload": {"args": {}}},
            )
            try:
                frame = await anext(source)
                assert "clientId" in frame
                ready.set()
                await anyio.sleep_forever()
            finally:
                await source.aclose()

        async with anyio.create_task_group() as group:
            group.start_soon(subscribe)
            with anyio.fail_after(5):
                await ready.wait()
            group.cancel_scope.cancel()
        assert worker.process.poll() is None
        assert worker.request("plugin-capabilities", pluginId="fixture") == {
            "providesModels": False,
            "settingsNamespaces": [],
        }
        assert not worker.pending
        # Disconnect can arrive before a saturated thread pool sends the open.
        worker.control("cancel-call", id="cancel-before-open")
        with pytest.raises(ValueError, match="cancelled before dispatch"):
            worker.request(
                "plugin-rpc-stream",
                streamId="cancel-before-open",
                channel="/api",
                method="$events",
                payload={"args": {}},
                timeout=2,
            )
        assert worker.process.poll() is None

    try:
        anyio.run(verify)
    finally:
        worker.close()


def test_model_parameter_negotiation_is_generic_cached_and_keeps_tools():
    seen = []
    tools = [{"type": "function", "function": {"name": "read_file"}}]

    def respond(request):
        payload = json.loads(request.content)
        seen.append(payload)
        if "temperature" in payload:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "unsupported_parameter",
                        "param": "temperature",
                        "message": "Not supported",
                    }
                },
            )
        if "max_tokens" in payload:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "unsupported_parameter",
                        "param": "max_tokens",
                        "message": "Use max_completion_tokens instead",
                    }
                },
            )
        assert payload["max_completion_tokens"] == 4096
        assert payload["tools"] == tools
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ready"}, "finish_reason": "stop"}]}
        )

    async def verify():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            body = {
                "model": "arbitrary-new-model",
                "temperature": 0.2,
                "max_tokens": 4096,
                "tools": tools,
                "messages": [{"role": "user", "content": "Read the file"}],
            }
            for _ in range(2):
                async with compatible_model_stream(
                    client, "POST", "https://parameter-fixture.test/chat/completions", json=body
                ) as response:
                    assert response.status_code == 200
                    assert await response.aread()
            assert body["temperature"] == 0.2
            assert "max_completion_tokens" not in body

    asyncio.run(verify())
    assert len(seen) == 4
    assert "temperature" not in seen[-1]


@pytest.mark.parametrize("status,param", [(401, "temperature"), (400, "tools"), (422, "messages")])
def test_model_negotiation_does_not_hide_authentication_or_required_capabilities(status, param):
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            status,
            json={
                "error": {
                    "code": "unsupported_parameter",
                    "param": param,
                    "message": "Not supported",
                }
            },
        )

    async def verify():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            async with compatible_model_stream(
                client,
                "POST",
                f"https://required-fixture.test/{status}/{param}",
                json={
                    "model": "generic-model",
                    "temperature": 0.2,
                    "tools": [{}],
                    "messages": [{}],
                },
            ) as response:
                assert response.status_code == status

    asyncio.run(verify())
    assert len(seen) == 1


def test_model_text_blocks_and_object_tool_arguments_are_normalized():
    packet = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": "Hello"},
                        {"type": "text", "text": {"value": " world"}},
                    ],
                    "reasoning": [{"text": "Working"}],
                    "tool_calls": [
                        {
                            "id": "call",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": {"path": "test/a.txt"}},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }

    class Response:
        async def aiter_lines(self):
            yield "data: " + json.dumps(packet)
            yield "data: [DONE]"

    async def verify():
        lines = [line async for line in model_stream_lines(Response(), 5)]
        delta = json.loads(lines[0][5:])["choices"][0]["delta"]
        assert delta["content"] == "Hello world"
        assert delta["reasoning_content"] == "Working"
        assert json.loads(delta["tool_calls"][0]["function"]["arguments"]) == {"path": "test/a.txt"}

    asyncio.run(verify())


def test_plugin_binary_upload_keeps_origin_guard_and_core_json_contract(tmp_path):
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "binary-fixture",
                "type": "module",
                "microMulti": {"cordis": {"entry": "host.mjs"}},
            }
        ),
        encoding="utf-8",
    )
    (root / "host.mjs").write_text(
        "export const inject=['webServer'];export function apply(ctx){ctx.webServer.register({kind:'exact',path:'/api/fixture-binary',handler:async(req,res)=>{const chunks=[];for await(const chunk of req)chunks.push(chunk);res.writeHead(201,{'content-type':'application/json'});res.end(JSON.stringify({data:Buffer.concat(chunks).toString('base64'),type:req.headers['content-type']}));}});}",
        encoding="utf-8",
    )
    manifest = native_manifest(root)
    assert manifest
    app = create_app(tmp_path / "home")
    data = b"\x00\xffnative-plugin-upload"
    with TestClient(app) as client:
        app.state.service.store.put(
            "dsh_bundle",
            {
                "id": "binary-fixture",
                "name": "binary-fixture",
                "enabled": True,
                "native_manifest": manifest,
            },
        )
        response = client.post(
            "/api/fixture-binary",
            content=data,
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 201, response.text
        assert response.json() == {
            "data": base64.b64encode(data).decode(),
            "type": "application/octet-stream",
        }
        blocked = client.post(
            "/api/fixture-binary",
            content=data,
            headers={
                "content-type": "application/octet-stream",
                "origin": "https://untrusted.example",
            },
        )
        assert blocked.status_code == 403
        assert (
            client.post(
                "/api/conversations", content="title=x", headers={"content-type": "text/plain"}
            ).status_code
            == 415
        )


def test_plugin_websocket_subscriptions_keep_http_available(tmp_path, monkeypatch):
    """Long subscriptions must not occupy Chromium's six HTTP connections."""
    closed = []

    async def subscription(store, home, plugin_id, body):
        try:
            yield json.dumps({"value": {"id": plugin_id, "method": body["method"]}})
            await asyncio.Event().wait()
        finally:
            closed.append(plugin_id)

    monkeypatch.setattr("masp.plugin_surface.rpc_stream", subscription)
    with TestClient(create_app(tmp_path)) as client:
        from contextlib import ExitStack

        with ExitStack() as stack:
            for index in range(8):
                socket = stack.enter_context(
                    client.websocket_connect(
                        f"/api/dsh/plugins/fixture-{index}/rpc/socket",
                        headers={"origin": "http://testserver"},
                    )
                )
                socket.send_json({"channel": "/fixture", "method": "watch", "payload": {}})
                assert socket.receive_json()["value"]["id"] == f"fixture-{index}"
            assert client.get("/api/conversations").status_code == 200
        assert len(closed) == 8
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as blocked:
            with client.websocket_connect(
                "/api/dsh/plugins/fixture/rpc/socket", headers={"origin": "https://evil.test"}
            ):
                pass
        assert blocked.value.code == 1008


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required")
def test_generic_legacy_namespace_index_injections_and_custom_stream(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "protocol-fixture",
                "type": "module",
                "microMulti": {"cordis": {"entry": "host.mjs"}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "host.mjs").write_text(
        """
import Schema from '@deepseek-ai/schemastery';
export const inject=['settings','connection','webServer'];
export function apply(ctx){
 const settings=ctx.settings.register('fixture-preferences',Schema.object({enabled:Schema.boolean().default(true)}));
 if(settings.get().enabled!==ctx.settings.get('fixture-preferences').enabled)throw Error('Native namespace read failed');
 ctx.connection.rpc.handle('/fixture-settings',()=>({enabled:ctx.settings.get('fixture-preferences').enabled,scope:settings.get().enabled}));
 ctx.on('webserver/index-inject',table=>table.push({kind:'script',placement:'head',text:'globalThis.fixtureReady=true;'}));
 ctx.webServer.tapIndex(html=>html.replace('</body>','<aside>fixture-index</aside></body>'));
 ctx.connection.rpc.handle('/fixture-stream',async function*(method,payload,signal){yield {ready:true};});
}
""",
        encoding="utf-8",
    )
    manifest = native_manifest(tmp_path)
    assert manifest
    worker = CordisWorker(tmp_path / "home", manifest, tmp_path)
    try:
        html = "<html><head></head><body>" + "x" * 510000 + "</body></html>"
        rendered = worker.request("plugin-index", html=html)["html"]
        assert "globalThis.fixtureReady=true" in rendered
        assert "<aside>fixture-index</aside>" in rendered
        worker.request(
            "plugin-rpc-stream",
            channel="/fixture-stream",
            method="watch",
            payload={},
            streamId="fixture",
        )
        values = []
        while not worker.events.empty():
            packet = worker.events.get_nowait()
            if packet.get("event") == "plugin-stream-value":
                values.append(packet["value"])
        assert values == [{"ready": True}]
        view = worker.request(
            "plugin-rpc", channel="/api", method="settings/describe", payload={"args": {}}
        )
        assert "fixture-preferences" in json.dumps(view)
        saved = worker.request(
            "plugin-rpc",
            channel="/api",
            method="settings/update",
            payload={"args": {"ns": "fixture-preferences", "patch": {"enabled": False}}},
        )["result"]
        assert saved["ok"], saved
        assert worker.request("plugin-rpc", channel="/fixture-settings", method="read", payload={})[
            "result"
        ] == {"enabled": False, "scope": False}
        invalid = worker.request(
            "plugin-rpc",
            channel="/api",
            method="settings/update",
            payload={"args": {"ns": "fixture-preferences", "patch": {"enabled": "invalid"}}},
        )["result"]
        assert not invalid["ok"]
        assert (
            json.loads((tmp_path / "home/native-namespace-settings.json").read_text())[
                "fixture-preferences"
            ]["enabled"]
            is False
        )
        worker.close()
        worker = CordisWorker(tmp_path / "home", manifest, tmp_path)
        assert worker.request("plugin-rpc", channel="/fixture-settings", method="read", payload={})[
            "result"
        ] == {"enabled": False, "scope": False}

    finally:
        worker.close()
