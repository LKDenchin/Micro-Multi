"""Real permission handshakes, attachments, compaction and long-work regressions."""

import asyncio
import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_autonomous_collaboration import Response, call, config

from masp.api import create_app
from masp.attachments import prepare_attachments
from masp.chat_tools import CHAT_TOOLS, run_chat_tool
from masp.domain import ChatMessageCreate
from masp.permissions import ApprovalBroker
from masp.storage import Store
from masp.supervisor import SupervisorManager
from masp.work_budget import WorkBudget, compact_runtime_messages


@pytest.mark.parametrize(
    "mode,name,needs_approval",
    [
        ("read", "read_file", False),
        ("read", "write_file", True),
        ("read", "run_command", True),
        ("files", "read_file", False),
        ("files", "write_file", False),
        ("files", "run_command", True),
        ("commands", "write_file", False),
        ("commands", "run_command", False),
        ("read", "external_plugin", True),
    ],
)
def test_permissions_are_operation_scoped(tmp_path, mode, name, needs_approval):
    async def run():
        broker = ApprovalBroker(Store(tmp_path / "db.sqlite"))
        events = []

        async def emit(kind, payload):
            events.append(payload)

        task = asyncio.create_task(
            broker.authorize("conv", name, '{"path":"test.txt"}', mode, asyncio.Event(), emit)
        )
        await asyncio.sleep(0.01)
        if needs_approval:
            assert not task.done()
            event = events[0]
            assert event["path"] == "test.txt"
            with pytest.raises(ValueError):
                broker.decide("other", event["id"], True, "commands")
            if event["required_mode"] == "commands":
                with pytest.raises(ValueError):
                    broker.decide("conv", event["id"], True, "files")
            broker.decide("conv", event["id"], True, event["required_mode"])
            assert await task is True
            with pytest.raises(ValueError):
                broker.decide("conv", event["id"], True, "commands")
            second = asyncio.create_task(
                broker.authorize("conv", name, "[]", mode, asyncio.Event(), emit)
            )
            await asyncio.sleep(0.01)
            assert not second.done()
            broker.decide("conv", events[-1]["id"], False, "read")
            assert await second is False
        else:
            assert await task is True
            assert not events

    asyncio.run(run())


def test_cancelled_approval_cannot_execute(tmp_path):
    async def run():
        broker = ApprovalBroker(Store(tmp_path / "db.sqlite"))
        cancel = asyncio.Event()

        async def emit(*args):
            cancel.set()

        assert not await broker.authorize("c", "write_file", "{}", "read", cancel, emit)
        assert not broker.pending

    asyncio.run(run())


def test_image_and_binary_attachments_preserve_bytes_and_do_not_overwrite(tmp_path):
    data = b"\x89PNG\r\n\x1a\nimage"

    def make():
        return {
            "name": "clipboard.png",
            "data_url": "data:image/png;base64," + base64.b64encode(data).decode(),
        }

    first, second = make(), make()
    images = prepare_attachments([first], tmp_path, "conv")
    prepare_attachments([second], tmp_path, "conv")
    assert images[0]["type"] == "image_url"
    assert first["workspace_path"] != second["workspace_path"]
    assert (tmp_path / first["workspace_path"]).read_bytes() == data
    binary = {
        "name": "data.zip",
        "data_url": "data:application/zip;base64," + base64.b64encode(b"zip").decode(),
    }
    assert prepare_attachments([binary], tmp_path, "conv") == []
    assert (tmp_path / binary["workspace_path"]).read_bytes() == b"zip"
    with pytest.raises(ValueError):
        prepare_attachments([{"data_url": "data:image/png;base64,broken"}], tmp_path, "conv")


def test_runtime_compaction_preserves_original_goal_and_complete_tool_pairs():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "ORIGINAL REQUIREMENT"},
    ]
    for i in range(20):
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": f"c{i}", "function": {"name": "write_file", "arguments": "{}"}}
                    ],
                },
                {"role": "tool", "tool_call_id": f"c{i}", "content": f"wrote file-{i}.py"},
            ]
        )
    assert compact_runtime_messages(messages, 1000, force=True)
    assert messages[1]["content"] == "ORIGINAL REQUIREMENT"
    assert "<compacted-summary>" in messages[2]["content"]
    assert "file-14.py" in messages[2]["content"]
    for index, msg in enumerate(messages):
        if msg["role"] == "tool":
            assert msg["tool_call_id"] in {c["id"] for c in messages[index - 1]["tool_calls"]}


def test_eight_hour_budget_uses_elapsed_time(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("masp.work_budget.time.monotonic", lambda: clock[0])
    budget = WorkBudget(28800, started=100)
    clock[0] += 28799
    assert budget.remaining == 1 and not budget.exhausted
    clock[0] += 1
    assert budget.exhausted
    assert ChatMessageCreate(content="task").autonomous_hours == 8
    with pytest.raises(ValueError):
        ChatMessageCreate(content="task", autonomous_hours=9)


def test_unicode_verification_command_works_on_windows(tmp_path):
    result = json.loads(
        run_chat_tool(
            tmp_path,
            "run_command",
            json.dumps({"command": "python -c \"print('✓✅')\""}),
            access_mode="commands",
        )
    )
    assert result["exit_code"] == 0
    assert "✓✅" in result["stdout"]


def test_worker_exceeds_old_iteration_cap_and_keeps_original_request(tmp_path):
    async def run():
        requests = []

        class Client:
            def stream(self, *args, **kwargs):
                payload = json.loads(json.dumps(kwargs["json"]))
                requests.append(payload)
                if len(requests) <= 55:
                    return Response(
                        {
                            "tool_calls": [
                                call(
                                    "write_file",
                                    {"path": f"step-{len(requests)}.txt", "content": "done"},
                                )
                            ]
                        }
                    )
                return Response({"content": "Delivered all files [r55 write_file]"})

        async def emit(*args):
            pass

        mgr = SupervisorManager(tmp_path, "long-work")
        report = await mgr.execute_subagent_task(
            "worker",
            "Create all 55 files",
            client=Client(),
            default_config=config(),
            load_model_config=lambda _: config(),
            sub_tools=CHAT_TOOLS,
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
            max_turns=1000000,
            task_timeout_seconds=28800,
            batch_steps=10,
            context_max_chars=10000,
        )
        assert report["status"] == "completed"
        assert len(requests) == 56
        assert len(list(tmp_path.glob("step-*.txt"))) == 55
        assert any("<compacted-summary>" in str(m.get("content")) for m in requests[-1]["messages"])
        assert any("Create all 55 files" in str(m.get("content")) for m in requests[-1]["messages"])

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode,tool,args",
    [
        ("read", "write_file", {"path": "approved.txt", "content": "approved once"}),
        ("files", "run_command", {"command": "python -c \"print('confirmed')\""}),
    ],
)
def test_real_api_approval_waits_then_executes_once(tmp_path, monkeypatch, mode, tool, args):
    import time
    from concurrent.futures import ThreadPoolExecutor

    calls = []
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)

    def stream(self, *a, **kw):
        calls.append(kw["json"])
        if len(calls) == 1:
            return Response({"tool_calls": [call(tool, args)]})
        return Response({"content": "Operation completed [r1 " + tool + "]"})

    async def no_title(*a, **kw):
        raise RuntimeError("no title endpoint")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "test", "model": "test", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
        url = f"/api/conversations/{conv['id']}"
        with ThreadPoolExecutor() as pool:
            turn = pool.submit(
                client.post,
                url + "/messages",
                json={
                    "content": "Execute requested operation",
                    "main_only": True,
                    "access_mode": mode,
                },
            )
            for _ in range(200):
                pending = app.state.service.store.list("approval", conv["id"])
                if pending:
                    break
                time.sleep(0.01)
            assert pending and not turn.done()
            approval = pending[0]
            assert not (tmp_path / "home" / "temporary" / conv["id"] / "approved.txt").exists()
            grant = client.post(
                url + "/approvals/" + approval["id"],
                json={"allow": True, "mode": approval["required_mode"]},
            )
            assert grant.status_code == 200
            response = turn.result(timeout=10)
            assert "event: approval_required" in response.text
            assert "Operation completed" in response.text
            assert (
                client.post(
                    url + "/approvals/" + approval["id"], json={"allow": True, "mode": "commands"}
                ).status_code
                == 409
            )
            if tool == "write_file":
                assert (
                    tmp_path / "home" / "temporary" / conv["id"] / "approved.txt"
                ).read_text() == "approved once"
            else:
                assert "confirmed" in response.text


@pytest.mark.parametrize("solo", [True, False])
def test_lead_continues_past_50_steps_until_completion(tmp_path, monkeypatch, solo):
    requests = []
    lead_requests = []
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)

    def stream(self, *a, **kw):
        payload = json.loads(json.dumps(kw["json"]))
        requests.append(payload)
        if "自主子代理" in payload["messages"][0]["content"]:
            return Response({"content": "建议按编号创建文件；实施交给主代理。"})
        lead_requests.append(payload)
        if len(lead_requests) <= 55:
            return Response(
                {
                    "tool_calls": [
                        call(
                            "write_file",
                            {"path": f"part-{len(lead_requests)}.txt", "content": "done"},
                        )
                    ]
                }
            )
        return Response({"content": "Completed all requested files [r55 write_file]"})

    async def no_title(*a, **kw):
        raise RuntimeError("no title endpoint")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    with TestClient(create_app(tmp_path / "home")) as client:
        project = client.post("/api/projects", json={"name": "long task"}).json()
        profile = client.post(
            "/api/model-profiles",
            json={"name": "test", "model": "test", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post(
            "/api/conversations",
            json={"project_id": project["id"], "model_profile_id": profile["id"]},
        ).json()
        response = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={
                "content": "Create all 55 files",
                "main_only": solo,
                "access_mode": "commands",
                "autonomous_hours": 8,
            },
        )
        assert response.status_code == 200 and "Completed all requested files" in response.text
        assert len(requests) == 56 if solo else len(requests) > 56
        assert len(list(Path(project["repository"]).glob("part-*.txt"))) == 55
        assert any("<compacted-summary>" in str(m.get("content")) for m in requests[-1]["messages"])


def test_attachment_vision_payload_and_saved_path(tmp_path, monkeypatch):
    requests = []
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)

    def stream(self, *a, **kw):
        requests.append(json.loads(json.dumps(kw["json"])))
        return Response({"content": "Image received"})

    async def no_title(*a, **kw):
        raise RuntimeError("no title endpoint")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "vision", "model": "vision", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
        data_url = "data:image/png;base64," + base64.b64encode(b"image bytes").decode()
        assert (
            client.post(
                f"/api/conversations/{conv['id']}/messages",
                json={
                    "content": "inspect",
                    "attachments": [{"name": "image.png", "data_url": data_url}],
                },
            ).status_code
            == 200
        )
        content = next(
            request["messages"][-1]["content"]
            for request in requests
            if isinstance(request["messages"][-1]["content"], list)
        )
        assert content[1]["image_url"]["url"] == data_url
        messages = client.get(f"/api/conversations/{conv['id']}/messages").json()
        saved = next(m for m in messages if m["role"] == "user")["attachments"][0]
        assert saved["workspace_path"] in content[0]["text"]
        assert (
            tmp_path / "home" / "temporary" / conv["id"] / saved["workspace_path"]
        ).read_bytes() == b"image bytes"


def test_compaction_archives_full_transcript_and_original_constraints(tmp_path):
    from masp.compaction import build_deterministic_summary

    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}).json()
        records = []
        for i in range(24):
            record = {
                "id": f"msg-{i}",
                "role": "user" if i % 2 == 0 else "assistant",
                "content": (
                    "Original goal\n" + "context\n" * 150 + "必须使用 PySide6 并保留所有历史记录"
                    if i == 0
                    else f"step {i}"
                ),
                "created_at": f"2026-10-01T00:00:{i:02d}",
            }
            app.state.service.store.put("message", record, conv["id"])
            records.append(record)
        assert "PySide6" in build_deterministic_summary(records)
        result = client.post(f"/api/conversations/{conv['id']}/compact", json={})
        assert result.status_code == 200 and result.json()["compacted"]
        restored = client.get(f"/api/conversations/{conv['id']}/messages").json()
        assert {m["id"] for m in restored} == {m["id"] for m in records}
        assert next(m for m in restored if m["id"] == "msg-0")["content"] == records[0]["content"]


def test_stream_identifiers_accept_fragments_and_cumulative_names():
    from masp.model_runtime import merge_stream_identifier

    assert merge_stream_identifier("write_", "file") == "write_file"
    assert merge_stream_identifier("write_file", "write_file") == "write_file"
    assert merge_stream_identifier("call_1", "call_1") == "call_1"
    assert merge_stream_identifier("write_", "write_file") == "write_file"


def test_worker_repeated_tool_loop_stops_before_time_limit(tmp_path):
    async def run():
        count = 0

        class Client:
            def stream(self, *args, **kwargs):
                nonlocal count
                count += 1
                return Response({"tool_calls": [call("list_files", {})]})

        async def emit(*args):
            pass

        mgr = SupervisorManager(tmp_path, "repeated")
        report = await mgr.execute_subagent_task(
            "worker",
            "Inspect workspace",
            client=Client(),
            default_config=config(),
            load_model_config=lambda _: config(),
            sub_tools=CHAT_TOOLS,
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
            max_turns=1000000,
            task_timeout_seconds=28800,
        )
        assert report["status"] == "failed" and count == 8
        assert "8" in report["error"]

    asyncio.run(run())


def test_lead_time_limit_preserves_partial_output(tmp_path, monkeypatch):
    class TinyBudget:
        def __init__(self, seconds):
            assert seconds == 28800

        remaining = 0.15
        exhausted = False

    class Slow(Response):
        async def aiter_lines(self):
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": "saved partial reply"}}]}
            )
            await asyncio.sleep(2)

    monkeypatch.setattr("masp.api.WorkBudget", TinyBudget)
    monkeypatch.setattr("httpx.AsyncClient.stream", lambda *a, **kw: Slow())
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "test", "model": "test", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
        response = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"content": "hello", "autonomous_hours": 8},
        )
        assert "时间上限" in response.text
        saved = client.get(f"/api/conversations/{conv['id']}/messages").json()
        assert any("saved partial reply" in m["content"] for m in saved if m["role"] == "assistant")


def test_builtin_mcp_permissions_follow_underlying_operation(tmp_path):
    async def run():
        broker = ApprovalBroker(Store(tmp_path / "db.sqlite"))

        async def unexpected(*args):
            raise AssertionError("read/file grant should be automatic")

        assert await broker.authorize(
            "c", "mcp__builtin__git_status", "{}", "read", asyncio.Event(), unexpected, "git_status"
        )
        assert await broker.authorize(
            "c",
            "mcp__builtin__write_workspace_file",
            "{}",
            "files",
            asyncio.Event(),
            unexpected,
            "write_workspace_file",
        )
        events = []

        async def emit(kind, payload):
            events.append(payload)

        task = asyncio.create_task(
            broker.authorize(
                "c",
                "mcp__builtin__run_workspace_command",
                "{}",
                "files",
                asyncio.Event(),
                emit,
                "run_workspace_command",
            )
        )
        await asyncio.sleep(0.01)
        assert events[0]["required_mode"] == "commands" and not task.done()
        broker.decide("c", events[0]["id"], False, "files")
        assert not await task

    asyncio.run(run())


def test_worker_respects_disabled_compaction(tmp_path):
    async def run():
        requests = []

        class Client:
            def stream(self, *args, **kwargs):
                requests.append(json.loads(json.dumps(kwargs["json"])))
                if len(requests) <= 20:
                    return Response(
                        {
                            "tool_calls": [
                                call(
                                    "write_file",
                                    {"path": f"item-{len(requests)}.txt", "content": "written"},
                                )
                            ]
                        }
                    )
                return Response({"content": "Delivered [r20 write_file]"})

        async def emit(*args):
            pass

        mgr = SupervisorManager(tmp_path, "no-compact")
        report = await mgr.execute_subagent_task(
            "worker",
            "Create files",
            client=Client(),
            default_config=config(),
            load_model_config=lambda _: config(),
            sub_tools=CHAT_TOOLS,
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
            max_turns=30,
            auto_compact=False,
            context_max_chars=100,
            batch_steps=2,
        )
        assert report["status"] == "completed"
        assert not any(
            "<compacted-summary>" in str(m.get("content")) for m in requests[-1]["messages"]
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "tool,args",
    [
        ("write_file", {"path": "resumed.txt", "content": "working"}),
        (
            "run_command",
            {
                "command": "python -c \"from pathlib import Path; Path('resumed.txt').write_text('working')\""
            },
        ),
    ],
)
def test_stopped_pause_then_compact_does_not_block_next_tool_turn(
    tmp_path, monkeypatch, tool, args
):
    requests = []
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)

    def stream(self, *a, **kw):
        requests.append(kw["json"])
        if len(requests) == 1:
            return Response({"tool_calls": [call(tool, args)]})
        return Response({"content": "Resumed successfully [r1 write_file]"})

    async def no_title(*a, **kw):
        raise RuntimeError("offline")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "test", "model": "test", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
        url = f"/api/conversations/{conv['id']}"
        assert client.post(url + "/pause", json={}).status_code == 200
        assert client.post(url + "/cancel", json={}).status_code == 200
        assert client.post(url + "/compact", json={}).status_code == 200
        result = client.post(
            url + "/messages",
            json={
                "content": "Continue",
                "main_only": True,
                "access_mode": "commands",
                "autonomous_hours": 0.01,
            },
        )
        assert "Resumed successfully" in result.text
        assert (
            tmp_path / "home" / "temporary" / conv["id"] / "resumed.txt"
        ).read_text() == "working"
