"""Real Cordis/ToolRuntime execution, lifecycle and crash boundary tests (no JS stubs)."""

import ctypes
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from masp.cordis_runtime import CordisWorker, close_native_hosts, inspect_native, native_manifest
from masp.plugin_tools import (
    discover_plugins,
    execute_plugin,
    install_dsh_plugin_from_path,
    remove_extension_bundle,
    set_extension_enabled,
)
from masp.storage import Store


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "native-source"
    shutil.copytree(Path(__file__).parents[1] / "examples" / "native-cordis", root)
    file = root / "counter.mjs"
    content = file.read_text().replace(
        "import { Service }", "import fs from 'node:fs';\nimport { Service }"
    )
    content = content.replace(
        "this.value=config.start??0;",
        "this.value=config.start??0; const workspace=ctx.microMulti.workspace; ctx.effect(()=>()=>fs.appendFileSync(workspace+'/disposed.txt','disposed\\n')); console.log('native plugin loaded');",
    )
    file.write_text(
        content.replace("extends Service {", "extends Service { static inject=['microMulti'];")
    )
    yield root
    close_native_hosts()


def test_native_services_events_state_workspace_and_disposal(tmp_path, source):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    bundle = install_dsh_plugin_from_path(store, home, str(source))
    assert bundle["runtime"] == "native-cordis-host"
    assert bundle["native_versions"]["cordis"] == "4.0.4"
    assert (source / "disposed.txt").read_text() == "disposed\n"  # probe always tears down
    tool = next(iter(discover_plugins(store)[1].values()))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = json.loads(execute_plugin(tool, '{"label":"first"}', workspace, store))
    second = json.loads(execute_plugin(tool, '{"label":"second"}', workspace, store))
    assert first["value"] == first["event"] == 11 and second["value"] == second["event"] == 12
    assert first["workspace"] == str(workspace.resolve())
    other = tmp_path / "other"
    other.mkdir()
    assert json.loads(execute_plugin(tool, '{"label":"isolated"}', other, store))["value"] == 11
    set_extension_enabled(store, bundle["id"], False)
    assert (workspace / "disposed.txt").read_text() == "disposed\n"
    assert (other / "disposed.txt").read_text() == "disposed\n"
    assert discover_plugins(store)[0] == []
    with pytest.raises(ValueError, match="禁用"):
        execute_plugin(tool, '{"label":"blocked"}', workspace, store)
    set_extension_enabled(store, bundle["id"], True)
    assert (
        json.loads(execute_plugin(tool, '{"label":"restarted"}', workspace, store))["value"] == 11
    )
    remove_extension_bundle(store, bundle["id"])
    assert (workspace / "disposed.txt").read_text() == "disposed\ndisposed\n"
    assert discover_plugins(store)[0] == []


def test_missing_dependency_rejects_install_and_keeps_inventory(tmp_path, source):
    tool = source / "tool.mjs"
    tool.write_text(
        tool.read_text().replace(
            "'nativeCounter','microMulti'", "'nativeCounter','microMulti','missingHarnessService'"
        )
    )
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    with pytest.raises(ValueError, match="missingHarnessService"):
        install_dsh_plugin_from_path(store, home, str(source))
    assert not store.list("dsh_bundle") and not store.list("plugin")


def test_native_crash_and_sync_hang_only_stop_worker(tmp_path, source):
    tool = source / "tool.mjs"
    tool.write_text(
        tool.read_text().replace(
            "async execute(args){",
            "async execute(args){if(args.label==='crash')process.exit(17); if(args.label==='hang')while(true){};",
        )
    )
    manifest = native_manifest(source)
    worker = CordisWorker(tmp_path, manifest, source)
    try:
        with pytest.raises(ValueError, match="process exited"):
            worker.request("call", name="native_counter", arguments={"label": "crash"})
        worker.process.wait(timeout=3)
        assert worker.process.returncode == 17
    finally:
        worker.close()
    worker = CordisWorker(tmp_path, manifest, source)
    try:
        with pytest.raises(TimeoutError, match="not retried"):
            worker.request("call", timeout=0.3, name="native_counter", arguments={"label": "hang"})
        assert worker.process.poll() is not None
    finally:
        worker.close()
    healthy = inspect_native(tmp_path, manifest)
    assert healthy["tools"][0]["name"] == "native_counter"


def test_native_argument_validation_and_config_error(tmp_path, source):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    install_dsh_plugin_from_path(store, home, str(source))
    tool = next(iter(discover_plugins(store)[1].values()))
    with pytest.raises(ValueError, match="arguments are invalid"):
        execute_plugin(tool, '{"label":5}', source, store)
    package = json.loads((source / "package.json").read_text())
    package["microMulti"]["cordis"]["plugins"][0]["entry"] = "../outside.mjs"
    (source / "package.json").write_text(json.dumps(package))
    with pytest.raises(ValueError, match="inside the package"):
        native_manifest(source)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job object integration")
def test_backend_termination_kills_native_host(tmp_path, source):
    code = """import json,time,sys
from pathlib import Path
from masp.cordis_runtime import CordisWorker,native_manifest
worker=CordisWorker(Path(sys.argv[1]),native_manifest(Path(sys.argv[2])),Path(sys.argv[2]))
print(worker.process.pid,flush=True)
time.sleep(60)
"""
    backend = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", code, str(tmp_path), str(source)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        pid = int(backend.stdout.readline())
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        assert handle
        try:
            backend.kill()
            backend.wait(timeout=5)
            assert kernel.WaitForSingleObject(handle, 5000) == 0
        finally:
            kernel.CloseHandle(handle)
    finally:
        if backend.poll() is None:
            backend.kill()
        backend.communicate(timeout=5)


@pytest.mark.parametrize("allow", [True, False])
def test_native_chat_uses_real_exact_operation_approval(tmp_path, source, monkeypatch, allow):
    import time
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient
    from test_autonomous_collaboration import Response, call

    from masp.api import create_app

    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)

    def stream(self, *a, **kw):
        request = kw["json"]
        if request["messages"][-1]["role"] != "tool":
            alias = next(
                tool["function"]["name"]
                for tool in request["tools"]
                if tool["function"]["name"].startswith("plugin_plugin_")
            )
            return Response({"tool_calls": [call(alias, {"label": "confirmed"})]})
        return Response({"content": "Native operation handled"})

    async def no_title(*a, **kw):
        raise RuntimeError("offline")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        installed = client.post("/api/dsh/plugins/install", json={"path": str(source)})
        assert installed.status_code == 201 and installed.json()["runtime"] == "native-cordis-host"
        profile = client.post(
            "/api/model-profiles",
            json={"name": "mock", "model": "mock", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
        url = "/api/conversations/" + conv["id"]
        with ThreadPoolExecutor() as pool:
            turn = pool.submit(
                client.post,
                url + "/messages",
                json={"content": "Run native tool", "main_only": True, "access_mode": "read"},
            )
            pending = []
            for _ in range(200):
                pending = app.state.service.store.list("approval", conv["id"])
                if pending:
                    break
                time.sleep(0.01)
            assert pending and not turn.done()
            approval = pending[0]
            assert approval["required_mode"] == "commands"
            workspace = tmp_path / "home" / "temporary" / conv["id"]
            assert not (workspace / "disposed.txt").exists()
            grant = client.post(
                url + "/approvals/" + approval["id"], json={"allow": allow, "mode": "commands"}
            )
            assert grant.status_code == 200
            result = turn.result(timeout=10)
            assert "event: complete" in result.text and "Native operation handled" in result.text
            close_native_hosts(app.state.service.store)
            assert (workspace / "disposed.txt").exists() == allow
            if allow:
                assert '"value": 11' in result.text or '\\"value\\": 11' in result.text
            assert (
                client.post(
                    url + "/approvals/" + approval["id"], json={"allow": True, "mode": "commands"}
                ).status_code
                == 409
            )


@pytest.mark.skipif(os.name != "nt", reason="Windows Electron bundled Node")
def test_desktop_bundled_node_can_run_native_host(tmp_path, source, monkeypatch):
    electron = Path(__file__).parents[1] / "node_modules" / "electron" / "dist" / "electron.exe"
    if not electron.is_file():
        pytest.skip("Electron not installed")
    monkeypatch.setenv("MICRO_MULTI_NODE", str(electron))
    result = inspect_native(tmp_path, native_manifest(source))
    assert result["runtime"] == "native-cordis-host"
    assert result["tools"][0]["name"] == "native_counter"


@pytest.mark.parametrize("suffix", ["mjs", "cjs"])
def test_standard_package_entry_without_custom_manifest(tmp_path, suffix):
    root = tmp_path / "standard"
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "standard-cordis",
                "type": "module",
                "main": "index." + suffix,
                "peerDependencies": {"@deepseek-ai/cordis": "4.0.4"},
            }
        )
    )
    imports = (
        "import {defineTool} from '@deepseek-ai/dsh-tools';"
        if suffix == "mjs"
        else "const {defineTool}=require('@deepseek-ai/dsh-tools');"
    )
    body = """const plugin=Object.assign(ctx=>{ctx.tools.register(defineTool({name:'standard',description:'standard package',parameters:{},output:{schema:{type:'string'},render:(_args,value)=>[{type:'text',text:value}]},async execute(){return 'native standard result';}}));},{inject:['tools']});"""
    exported = "export default plugin;" if suffix == "mjs" else "module.exports=plugin;"
    (root / ("index." + suffix)).write_text(imports + body + exported)
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    try:
        assert (
            install_dsh_plugin_from_path(store, home, str(root))["runtime"] == "native-cordis-host"
        )
        tool = next(iter(discover_plugins(store)[1].values()))
        assert "native standard result" in execute_plugin(tool, "{}", root, store)
    finally:
        close_native_hosts(store)


def test_native_config_schema_is_enforced(tmp_path, source):
    counter = source / "counter.mjs"
    counter.write_text(
        "import z from '@deepseek-ai/schemastery';\n"
        + counter.read_text().replace(
            "extends Service {", "extends Service { static Config=z.object({start:z.natural()});"
        )
    )
    package = json.loads((source / "package.json").read_text())
    package["microMulti"]["cordis"]["plugins"][0]["config"]["start"] = "invalid"
    (source / "package.json").write_text(json.dumps(package))
    with pytest.raises(ValueError, match="invalid config"):
        inspect_native(tmp_path, native_manifest(source))


def test_harness_result_contract_and_filesystem_skills(tmp_path, source):
    from masp.cordis_runtime import native_context_messages

    tool = source / "tool.mjs"
    text = tool.read_text().replace(
        "async execute(args){",
        "async execute(args,run){run.deferContext({id:'native-context',role:'user',source:{kind:'user'},content:[{type:'text',text:'preserved context'}]});run.concludeTurn();",
    )
    tool.write_text(text)
    skill = source / ".agents" / "skills" / "native-test"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: native-test\ndescription: Real filesystem skill\n---\nTest body."
    )
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    install_dsh_plugin_from_path(store, home, str(source))
    native = next(iter(discover_plugins(store)[1].values()))
    output = execute_plugin(native, '{"label":"contract"}', source, store)
    assert output.contract["concludesTurn"] is True
    assert output.contract["content"][0]["type"] == "text"
    assert native_context_messages(output.contract["additionalContexts"]) == [
        {"role": "user", "content": "preserved context"}
    ]
    worker = CordisWorker(home, native_manifest(source), source)
    try:
        assert any(item["name"] == "native-test" for item in worker.request("skills")["skills"])
    finally:
        worker.close()


def test_native_image_context_crosses_process_boundary(tmp_path, source):
    from masp.cordis_runtime import native_context_messages

    tool = source / "tool.mjs"
    text = tool.read_text()
    # The fixture plugin supplies an attachment provider in the shared Cordis Context.
    text = text.replace(
        "ctx.tools.register(",
        "ctx.provide('attachments',{async readImage(ref){return {ref,data:Buffer.from('native image bytes')};}});ctx.tools.register(",
    )
    text = text.replace(
        "async execute(args){",
        "async execute(args,run){run.deferContext({id:'native-image',role:'user',source:{kind:'user'},content:[{type:'text',text:'image context'},{type:'image',attachment:{attachmentId:'fixture',mediaType:'image/png',bytes:18,width:1,height:1}}]});",
    )
    tool.write_text(text)
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    install_dsh_plugin_from_path(store, home, str(source))
    native = next(iter(discover_plugins(store)[1].values()))
    output = execute_plugin(native, '{"label":"image"}', source, store)
    messages = native_context_messages(output.contract["additionalContexts"], home)
    assert messages[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert messages[0]["content"][0]["text"] == "image context"


def test_separate_bundles_share_services_and_survive_unrelated_unmount(tmp_path, source):
    service_source = tmp_path / "service-bundle"
    tool_source = tmp_path / "tool-bundle"
    shutil.copytree(source, service_source)
    shutil.copytree(source, tool_source)
    for root, name, entry in [
        (service_source, "service-only", "counter.mjs"),
        (tool_source, "tool-only", "tool.mjs"),
    ]:
        package = json.loads((root / "package.json").read_text())
        package["name"] = name
        package["microMulti"] = {
            "cordis": {
                "plugins": [
                    {"entry": entry, "config": {"start": 10} if entry == "counter.mjs" else {}}
                ]
            }
        }
        (root / "package.json").write_text(json.dumps(package))
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    service_bundle = install_dsh_plugin_from_path(store, home, str(service_source))
    tool_bundle = install_dsh_plugin_from_path(store, home, str(tool_source))
    native = next(iter(discover_plugins(store)[1].values()))
    assert json.loads(execute_plugin(native, '{"label":"one"}', source, store))["value"] == 11
    set_extension_enabled(store, tool_bundle["id"], False)
    set_extension_enabled(store, tool_bundle["id"], True)
    assert json.loads(execute_plugin(native, '{"label":"two"}', source, store))["value"] == 12
    set_extension_enabled(store, service_bundle["id"], False)
    with pytest.raises(ValueError, match="Cordis tool failed"):
        execute_plugin(native, '{"label":"unavailable"}', source, store)


def test_real_native_agent_session_persists_across_host_restart(tmp_path, source):
    tool = source / "tool.mjs"
    text = tool.read_text().replace(
        "'tools','nativeCounter','microMulti'",
        "'tools','nativeCounter','microMulti','agents','sessionPersistence'",
    )
    text = text.replace(
        "async execute(args){",
        "async execute(args){const handle=args.label==='create'?await ctx.agents.create({sessionId:'native-durable-test',meta:{cwd:ctx.microMulti.workspace}}):await ctx.agents.resume({resumeSessionId:'native-durable-test'});if(args.label==='create')handle.agent.session.append('user/message',{id:'native-persisted-message',role:'user',source:{kind:'user'},content:[{type:'text',text:'durable native message'}]},{surfaceOp:'append'});await handle.dispose();",
    )
    tool.write_text(text)
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    install_dsh_plugin_from_path(store, home, str(source))
    native = next(iter(discover_plugins(store)[1].values()))
    execute_plugin(native, '{"label":"create"}', source, store)
    assert list((home / "native-sessions").rglob("*.jsonl"))
    close_native_hosts(store)
    assert json.loads(execute_plugin(native, '{"label":"resume"}', source, store))["value"] == 11


@pytest.mark.parametrize("allow", [True, False, "cancel"])
def test_inner_native_approval_reaches_existing_broker_and_audits(
    tmp_path, source, monkeypatch, allow
):
    import time
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient
    from test_autonomous_collaboration import Response, call

    from masp.api import create_app

    tool = source / "tool.mjs"
    text = tool.read_text().replace(
        "'tools','nativeCounter','microMulti'",
        "'tools','nativeCounter','microMulti','agents','approval'",
    )
    text = "import fs from 'node:fs';\n" + text
    text = text.replace(
        "async execute(args){",
        "async execute(args,run){const handle=await ctx.agents.create({sessionId:'inner-native-decision',meta:{cwd:ctx.microMulti.workspace}});handle.agent.session.append('turn/start',{turn:0});let outcome;try{outcome=await ctx.approval.request({agent:handle.agent,toolName:'inner_write',callId:'exact-inner-call',reason:'Write inner-approved.txt',signal:run.signal});if(outcome==='allowed-once')fs.writeFileSync(ctx.microMulti.workspace+'/inner-approved.txt','authorized');handle.agent.session.append('turn/end',{turn:0,reason:{kind:'completed'}});}finally{await handle.dispose();}args.label=outcome;",
    )
    tool.write_text(text)
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)

    def stream(self, *args, **kwargs):
        request = kwargs["json"]
        if request["messages"][-1]["role"] != "tool":
            alias = next(
                tool["function"]["name"]
                for tool in request["tools"]
                if tool["function"]["name"].startswith("plugin_plugin_")
            )
            return Response({"tool_calls": [call(alias, {"label": "inner"})]})
        return Response({"content": "Inner native decision handled"})

    async def offline(*a, **kw):
        raise RuntimeError("offline title")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", offline)
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        assert (
            client.post("/api/dsh/plugins/install", json={"path": str(source)}).status_code == 201
        )
        profile = client.post(
            "/api/model-profiles",
            json={"name": "fixture", "model": "fixture", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
        url = "/api/conversations/" + conv["id"]
        with ThreadPoolExecutor() as pool:
            turn = pool.submit(
                client.post,
                url + "/messages",
                json={
                    "content": "Run the native operation",
                    "main_only": True,
                    "access_mode": "commands",
                },
            )
            try:
                pending = []
                for _ in range(300):
                    pending = app.state.service.store.list("approval", conv["id"])
                    if pending:
                        break
                    time.sleep(0.01)
                assert pending and not turn.done()
                approval = pending[0]
                assert (
                    approval["tool"] == "inner_write"
                    and json.loads(approval["arguments"])["callId"] == "exact-inner-call"
                )
                workspace = tmp_path / "home" / "temporary" / conv["id"]
                assert not (workspace / "inner-approved.txt").exists()
                if allow == "cancel":
                    assert client.post(url + "/cancel", json={}).status_code == 200
                else:
                    assert (
                        client.post(
                            url + "/approvals/" + approval["id"],
                            json={"allow": allow, "mode": "commands"},
                        ).status_code
                        == 200
                    )
                response = turn.result(timeout=15)
                assert (
                    "event: approval_required" in response.text
                    and "event: complete" in response.text
                )
                assert (workspace / "inner-approved.txt").exists() == (allow is True)
                close_native_hosts(app.state.service.store)
                logs = "".join(
                    path.read_text()
                    for path in (tmp_path / "home" / "native-sessions").rglob("*.jsonl")
                )
                assert "approval/asked" in logs and "approval/decided" in logs
                assert (
                    "cancelled" if allow == "cancel" else "allowed-once" if allow else "rejected"
                ) in logs
            finally:
                if not turn.done():
                    for request in app.state.service.store.list("approval", conv["id"]):
                        if request["status"] == "pending":
                            client.post(
                                url + "/approvals/" + request["id"],
                                json={"allow": False, "mode": "commands"},
                            )


def test_failed_native_result_retains_structured_contract(tmp_path, source):
    from masp.cordis_runtime import NativeToolFailure

    tool = source / "tool.mjs"
    tool.write_text(
        tool.read_text().replace(
            "async execute(args){", "async execute(args){throw Error('deliberate native failure');"
        )
    )
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    install_dsh_plugin_from_path(store, home, str(source))
    native = next(iter(discover_plugins(store)[1].values()))
    with pytest.raises(NativeToolFailure) as failure:
        execute_plugin(native, '{"label":"failure"}', source, store)
    assert failure.value.contract["isError"] is True
    assert "deliberate native failure" in json.dumps(failure.value.contract["content"])


def test_native_parallel_safe_calls_overlap_and_exclusive_barriers_hold(tmp_path, source):
    import re
    from concurrent.futures import ThreadPoolExecutor

    tool = source / "tool.mjs"
    text = tool.read_text().replace(
        "name:'native_counter',",
        "name:'native_counter',isConcurrencySafe:args=>args.label!=='exclusive',",
    )
    text = re.sub(
        r"async execute\(args\)\{return .*?;\}",
        "async execute(args){const start=Date.now();fs.writeFileSync(ctx.microMulti.workspace+'/'+args.label+'.started','');await new Promise(resolve=>setTimeout(resolve,250));return {value:start,event:Date.now(),label:args.label,workspace:ctx.microMulti.workspace};}",
        text,
    )
    tool.write_text("import fs from 'node:fs';\n" + text)
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    install_dsh_plugin_from_path(store, home, str(source))
    native = next(iter(discover_plugins(store)[1].values()))
    execute_plugin(native, '{"label":"warm"}', source, store)

    def call(label):
        return json.loads(execute_plugin(native, json.dumps({"label": label}), source, store))

    with ThreadPoolExecutor(max_workers=4) as pool:
        batch = list(pool.map(call, ["a", "b", "c", "d"]))
    assert max(item["value"] for item in batch) < min(item["event"] for item in batch)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(call, "before")
        import time

        deadline = time.monotonic() + 10
        while not (source / "before.started").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (source / "before.started").exists()
        exclusive = pool.submit(call, "exclusive")
        deadline = time.monotonic() + 10
        while not (source / "exclusive.started").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (source / "exclusive.started").exists()
        after = pool.submit(call, "after")
        early, middle, late = first.result(), exclusive.result(), after.result()
    assert middle["value"] >= early["event"] and late["value"] >= middle["event"]
    assert {item["label"] for item in batch} == {"a", "b", "c", "d"}


def test_concurrent_native_approvals_keep_request_ownership(tmp_path, source):
    import asyncio
    import re

    from masp.native_approval import NativeApprovalBridge, native_approval

    tool = source / "tool.mjs"
    text = tool.read_text().replace(
        "'tools','nativeCounter','microMulti'",
        "'tools','nativeCounter','microMulti','agents','approval'",
    )
    text = text.replace(
        "name:'native_counter',", "name:'native_counter',isConcurrencySafe:()=>true,"
    )
    text = re.sub(
        r"async execute\(args\)\{return .*?;\}",
        "async execute(args,run){const handle=await ctx.agents.create({sessionId:'decision-'+args.label,meta:{cwd:ctx.microMulti.workspace}});handle.agent.session.append('turn/start',{turn:0});try{const outcome=await ctx.approval.request({agent:handle.agent,toolName:'inner_write',callId:args.label,reason:args.label,signal:run.signal});handle.agent.session.append('turn/end',{turn:0,reason:{kind:'completed'}});return {value:0,event:0,label:outcome,workspace:ctx.microMulti.workspace};}finally{await handle.dispose();}}",
        text,
    )
    tool.write_text(text)
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    install_dsh_plugin_from_path(store, home, str(source))
    native = next(iter(discover_plugins(store)[1].values()))

    async def scenario():
        decisions = {}
        both = asyncio.Event()

        async def invoke(label, allowed):
            async def authorize(event):
                assert event["callId"] == label
                decisions[label] = event["approvalId"]
                if len(decisions) == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), 8)
                return allowed

            bridge = NativeApprovalBridge(authorize, lambda: 15, lambda: False)
            token = native_approval.set(bridge)
            try:
                result = await asyncio.to_thread(
                    execute_plugin, native, json.dumps({"label": label}), source, store
                )
                assert bridge.closed
                return json.loads(result)["label"]
            finally:
                native_approval.reset(token)
                bridge.close()

        result = await asyncio.gather(invoke("one", True), invoke("two", False))
        assert result == ["allowed-once", "rejected"]
        assert len(set(decisions.values())) == 2

    asyncio.run(scenario())
