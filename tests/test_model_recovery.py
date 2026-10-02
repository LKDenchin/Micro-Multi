"""Provider-accurate recovery, truncated-action safety and adopted upstream evidence."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from test_autonomous_collaboration import Response, call, config

from masp.api import create_app
from masp.chat_tools import CHAT_TOOLS
from masp.model_runtime import (
    configure_provider,
    evaluate_report,
    requests_execution,
    stamp_receipt,
)
from masp.supervisor import SupervisorManager


class FinishedResponse(Response):
    def __init__(self, delta, reason):
        super().__init__(delta)
        self.reason = reason

    async def aiter_lines(self):
        yield "data: " + json.dumps({"choices": [{"delta": self.delta}]})
        yield "data: " + json.dumps(
            {
                "choices": [{"delta": {}, "finish_reason": self.reason}],
                "usage": {"completion_tokens": 8192},
            }
        )
        yield "data: [DONE]"


@pytest.mark.parametrize("first", ["reasoning", "empty", "length", "plan"])
def test_lead_recovers_and_delivers_in_same_user_turn(tmp_path, monkeypatch, first):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *a: None)
    requests = []

    def stream(self, *a, **kw):
        payload = kw["json"]
        requests.append(payload)
        if len(requests) == 1:
            if first == "reasoning":
                return FinishedResponse(
                    {"reasoning_content": "I should create a real refraction demo."}, "stop"
                )
            if first == "empty":
                return FinishedResponse({}, "stop")
            if first == "plan":
                return FinishedResponse({"content": "我打算创建实验演示。"}, "stop")
            # Even valid JSON is unsafe if the provider reports truncation.
            return FinishedResponse(
                {
                    "tool_calls": [
                        call(
                            "write_file", {"path": "unsafe.html", "content": "incomplete artifact"}
                        )
                    ]
                },
                "length",
            )
        if payload["messages"][-1]["role"] == "tool":
            return FinishedResponse({"content": "演示已生成。"}, "stop")
        return FinishedResponse(
            {
                "tool_calls": [
                    call(
                        "write_file",
                        {"path": "index.html", "content": "<!doctype html><h1>光的折射</h1>"},
                    )
                ]
            },
            "tool_calls",
        )

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)

    async def no_title(*a, **kw):
        raise RuntimeError("no title endpoint")

    monkeypatch.setattr("httpx.AsyncClient.post", no_title)
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        profile = client.post(
            "/api/model-profiles",
            json={
                "name": "mock",
                "model": "deepseek-flash",
                "base_url": "https://api.deepseek.com/v1",
                "max_output_tokens": 1024,
            },
        ).json()
        project = client.post("/api/projects", json={"name": "refraction"}).json()
        conv = client.post(
            "/api/conversations",
            json={"project_id": project["id"], "model_profile_id": profile["id"]},
        ).json()
        response = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={
                "content": "制作一个物理实验演示，有关光的折射的",
                "access_mode": "files",
                "main_only": True,
            },
        )
        assert "演示已生成" in response.text
        assert "event: model_recovery" in response.text
        from pathlib import Path

        root = Path(project["repository"])
        assert (root / "index.html").exists()
        assert not (root / "unsafe.html").exists()
        assert all(r["tools"] and r["max_tokens"] == 1024 for r in requests)
        assert requests[0]["reasoning_effort"] == "low"
        assert requests[1]["thinking"] == {"type": "disabled"}
        msg = next(
            m
            for m in app.state.service.store.list("message", conv["id"])
            if m["role"] == "assistant"
        )
        assert msg["model_recovery"]
        assert msg["model_steps"][0]["finish_reason"] == ("length" if first == "length" else "stop")
        assert msg["termination_reason"] is None


def test_worker_preserves_provider_reasoning_and_verifiable_receipts(tmp_path):
    async def run():
        requests = []

        class Client:
            def stream(self, *a, **kw):
                payload = kw["json"]
                requests.append(json.loads(json.dumps(payload)))
                if len(requests) == 1:
                    return FinishedResponse({"reasoning_content": "incomplete thinking"}, "length")
                if payload["messages"][-1]["role"] != "tool":
                    return FinishedResponse(
                        {
                            "reasoning_content": "exact reasoning for tool round",
                            "tool_calls": [
                                call("write_file", {"path": "demo.py", "content": "value=1"})
                            ],
                        },
                        "tool_calls",
                    )
                assert (
                    payload["messages"][-2]["reasoning_content"] == "exact reasoning for tool round"
                )
                return FinishedResponse({"content": "已创建 demo.py [r1 write_file]"}, "stop")

        async def emit(*a):
            pass

        mgr = SupervisorManager(tmp_path, "recovery")
        report = await mgr.execute_subagent_task(
            "worker",
            "创建 demo.py",
            client=Client(),
            default_config=config(),
            load_model_config=lambda _: config(),
            sub_tools=CHAT_TOOLS,
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
            max_turns=5,
        )
        assert report["status"] == "completed"
        assert report["verification"]["citation_resolved"]
        assert report["receipts"][0]["tool_name"] == "write_file"
        assert report["model_recovery"][0]["reason"] == "model_length_capped"

    asyncio.run(run())


def test_upstream_verifier_detects_uncited_unknown_wrong_and_failed_evidence():
    receipt = stamp_receipt(1, "write_file", '{"path":"demo.py"}', "ok", "c1", False)
    assert evaluate_report("已创建 demo.py", [receipt])["no_citation_claims"]
    assert evaluate_report("已创建 [r9]", [receipt])["unknown"] == ["r9"]
    assert evaluate_report("已测试 [r1 run_command]", [receipt])["failed"]
    failed = stamp_receipt(1, "run_command", "{}", "error", "c1", True)
    assert evaluate_report("已测试 [r1 run_command]", [failed])["failed"]


def test_question_guard_and_non_deepseek_provider_remain_unchanged():
    assert not requests_execution("如何制作实验演示？")
    assert requests_execution("制作一个物理实验演示")
    payload = {"model": "other", "messages": []}
    configure_provider(payload, "https://other.test/v1", recovering=True)
    assert payload == {"model": "other", "messages": []}
