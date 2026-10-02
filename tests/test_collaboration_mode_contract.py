"""Explicit collaboration mode owns delegation and UI history persistence."""

import pytest
from fastapi.testclient import TestClient
from test_autonomous_collaboration import call
from test_model_recovery import FinishedResponse

from masp.api import create_app


@pytest.mark.parametrize("solo", [False, True])
def test_simple_request_requires_child_only_in_multi_mode(tmp_path, monkeypatch, solo):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    requests = []

    def stream(self, *args, **kwargs):
        requests.append(kwargs["json"])
        return FinishedResponse({"content": "递归是函数调用自身。"}, "stop")

    async def offline(*args, **kwargs):
        raise RuntimeError("offline title")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", offline)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "fixture", "model": "fixture", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conversation = client.post(
            "/api/conversations", json={"model_profile_id": profile["id"]}
        ).json()
        url = "/api/conversations/" + conversation["id"]
        response = client.post(url + "/messages", json={"content": "解释递归", "main_only": solo})
        assert response.status_code == 200
        saved = next(
            message
            for message in client.get(url + "/messages").json()
            if message["role"] == "assistant"
        )
        assert bool(saved["subagent_events"]) is not solo
        assert ("event: subagent_progress" in response.text) is not solo
        assert len(requests) == 1 if solo else len(requests) >= 2


def test_disabled_session_log_does_not_erase_tools_when_reopening_conversation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)

    def stream(self, *args, **kwargs):
        if kwargs["json"]["messages"][-1]["role"] == "tool":
            return FinishedResponse({"content": "已列出文件。"}, "stop")
        return FinishedResponse({"tool_calls": [call("list_files", {"path": "."})]}, "tool_calls")

    async def offline(*args, **kwargs):
        raise RuntimeError("offline title")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", offline)
    with TestClient(create_app(tmp_path / "home")) as client:
        client.put("/api/dsh/settings", json={"sessionLog": {"enabled": False}})
        profile = client.post(
            "/api/model-profiles",
            json={"name": "fixture", "model": "fixture", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conversation = client.post(
            "/api/conversations", json={"model_profile_id": profile["id"]}
        ).json()
        url = "/api/conversations/" + conversation["id"]
        client.post(
            url + "/messages",
            json={"content": "列出文件", "main_only": True, "access_mode": "commands"},
        )
        saved = next(
            message
            for message in client.get(url + "/messages").json()
            if message["role"] == "assistant"
        )
        assert saved["tool_events"]
        assert any(segment["type"] == "tools" for segment in saved["segments"])
