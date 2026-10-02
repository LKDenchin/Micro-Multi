"""A vision plugin receives durable paths while a text model receives text."""

import json

from fastapi.testclient import TestClient
from test_autonomous_collaboration import call
from test_model_recovery import FinishedResponse

from masp.api import create_app


def test_text_model_uses_registered_vision_tool_without_image_payload(tmp_path, monkeypatch):
    alias = "plugin_vision_fixture"
    plugin = {
        "id": "vision-fixture",
        "name": "vision_describe",
        "native_tool": "vision_describe",
        "runtime": "native-cordis-host",
        "description": "Look at images",
    }
    schema = {
        "type": "function",
        "function": {
            "name": alias,
            "description": "Describe image",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    monkeypatch.setattr("masp.api.discover_plugins", lambda *args: ([schema], {alias: plugin}))
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    seen = []

    def execute(_plugin, arguments, workspace, _store):
        args = json.loads(arguments)
        assert (workspace / args["paths"][0]).is_file()
        return "An image containing a single white pixel."

    monkeypatch.setattr("masp.api.execute_plugin", execute)

    def stream(self, *args, **kwargs):
        messages = kwargs["json"]["messages"]
        assert all(isinstance(message["content"], str) for message in messages)
        seen.append(messages)
        if messages[-1]["role"] == "tool":
            return FinishedResponse({"content": "图片是白色像素。"}, "stop")
        path = next(
            line
            for line in messages[-1]["content"].splitlines()
            if line.startswith(".attachments/")
        )
        return FinishedResponse(
            {"tool_calls": [call(alias, {"paths": [path], "question": "Describe the image"})]},
            "tool_calls",
        )

    async def offline(*args, **kwargs):
        raise RuntimeError("offline title")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", offline)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "text", "model": "text", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conversation = client.post(
            "/api/conversations", json={"model_profile_id": profile["id"]}
        ).json()
        response = client.post(
            "/api/conversations/" + conversation["id"] + "/messages",
            json={
                "content": "Describe this image",
                "main_only": True,
                "access_mode": "commands",
                "attachments": [
                    {
                        "name": "image.png",
                        "mime_type": "image/png",
                        "data_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=",
                    }
                ],
            },
        )
        assert response.status_code == 200
        assert "图片是白色像素" in response.text
        assert len(seen) == 2
