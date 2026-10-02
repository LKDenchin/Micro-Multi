"""Crash-safe turns and progress-aware recovery regressions."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from test_model_recovery import FinishedResponse

from masp.api import create_app
from masp.chat_tools import run_chat_tool
from masp.model_runtime import ModelRecovery, response_deadline
from masp.storage import Store, now
from masp.turn_journal import TurnJournal, recover_interrupted_turns


def test_journal_commits_visible_content_and_tools_before_finish(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.put("conversation", {"id": "c", "message_count": 0})
    journal = TurnJournal(store, "c", "m", now(), "mock")
    journal.consume('data: {"delta":"partial answer"}\n\n')
    journal.consume(
        'event: tool\ndata: {"name":"read_file","status":"complete","output":"checked"}\n\n'
    )
    reopened = Store(tmp_path / "db.sqlite")
    assert reopened.get("message", "m")["content"] == "partial answer"
    assert reopened.get("message", "m")["tool_events"][0]["output"] == "checked"
    recover_interrupted_turns(reopened)
    assert reopened.get("message", "m")["execution_status"] == "interrupted"
    assert reopened.get("conversation", "c")["execution_status"] == "interrupted"


def test_completed_journal_retains_final_metadata_and_does_not_duplicate(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.put("conversation", {"id": "c", "message_count": 0})
    journal = TurnJournal(store, "c", "m", now(), "mock")
    journal.consume('data: {"delta":"complete"}\n\n')
    store.update(
        "message", "m", turn_diff={"files": 1}, segments=[{"type": "text", "content": "complete"}]
    )
    journal.consume("event: complete\ndata: {}\n\n")
    journal.close()
    assert store.get("message", "m")["execution_status"] == "completed"
    assert store.get("message", "m")["turn_diff"] == {"files": 1}
    assert len(store.list("message", "c")) == 1


def test_output_budget_and_idle_timeout_are_separate():
    assert response_deadline(SimpleNamespace(timeout_seconds=90, max_output_tokens=8192)) > 800
    recovery = ModelRecovery(limit=1)
    assert recovery.continuation("model_length_capped")
    assert recovery.continuation("model_length_capped") is None
    recovery.success()
    assert recovery.continuation("model_length_capped")


def test_append_file_preserves_completed_chunks(tmp_path):
    first = run_chat_tool(
        tmp_path, "write_file", json.dumps({"path": "result.txt", "content": "first"})
    )
    second = run_chat_tool(
        tmp_path,
        "write_file",
        json.dumps({"path": "result.txt", "content": " second", "append": True}),
    )
    assert "error" not in json.loads(first)
    assert "error" not in json.loads(second)
    assert (tmp_path / "result.txt").read_text() == "first second"


def test_text_length_recovery_preserves_partial_in_next_request(tmp_path, monkeypatch):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)
    requests = []

    def stream(self, *args, **kwargs):
        messages = kwargs["json"]["messages"]
        requests.append(json.loads(json.dumps(messages)))
        if len(requests) == 1:
            return FinishedResponse({"content": "first half"}, "length")
        assert any(m.get("content") == "first half" and m["role"] == "assistant" for m in messages)
        return FinishedResponse({"content": "second half"}, "stop")

    async def no_title(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "mock", "model": "mock", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
        result = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"content": "解释一个问题", "agent_id": "main_only"},
        )
        assert "event: complete" in result.text
        messages = client.get(f"/api/conversations/{conv['id']}/messages").json()
        reply = next(m for m in messages if m["role"] == "assistant")
        assert "first half" in reply["content"] and "second half" in reply["content"]
        assert reply["execution_status"] == "completed"
        assert len(messages) == 2


def test_abrupt_backend_exit_keeps_partial_turn_on_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)
    home = tmp_path / "home"
    with TestClient(create_app(home)) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "mock", "model": "mock", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
    code = r"""
import asyncio,json,sys
from pathlib import Path
import httpx,keyring,uvicorn
from masp.api import create_app
keyring.get_password=lambda *args:None
class Response:
 status_code=200
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def aiter_lines(self):
  yield 'data: '+json.dumps({'choices':[{'delta':{'content':'durable partial reply'}}]})
  await asyncio.Event().wait()
httpx.AsyncClient.stream=lambda *args,**kwargs:Response()
uvicorn.run(create_app(Path(sys.argv[1])),host='127.0.0.1',port=int(sys.argv[2]),log_level='error')
"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(home), str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while True:
            assert process.poll() is None, "test backend exited before ready"
            try:
                if httpx.get(base + "/api/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert time.monotonic() < deadline
            time.sleep(0.05)
        with httpx.stream(
            "POST",
            base + f"/api/conversations/{conv['id']}/messages",
            json={"content": "解释测试", "agent_id": "main_only"},
            timeout=10,
        ) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if "durable partial reply" in line:
                    break
            else:
                raise AssertionError("provider never emitted partial reply")
            process.kill()
            process.wait(timeout=5)
        with TestClient(create_app(home)) as reopened:
            messages = reopened.get(f"/api/conversations/{conv['id']}/messages").json()
            reply = next(m for m in messages if m["role"] == "assistant")
            assert reply["content"] == "durable partial reply"
            assert reply["execution_status"] == "interrupted"
            assert len(messages) == 2
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_repeated_plans_without_execution_remain_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)
    requests = []

    def stream(self, *args, **kwargs):
        requests.append(kwargs["json"])
        return FinishedResponse({"content": "我计划创建网页。"}, "stop")

    async def no_title(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "mock", "model": "mock", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conv = client.post("/api/conversations", json={"model_profile_id": profile["id"]}).json()
        client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={"content": "创建一个网页", "agent_id": "main_only", "access_mode": "files"},
        )
        assert len(requests) == 3
        reply = next(
            m
            for m in client.get(f"/api/conversations/{conv['id']}/messages").json()
            if m["role"] == "assistant"
        )
        assert reply["execution_status"] == "failed"
        assert reply["termination_reason"] == "no_execution_evidence"
