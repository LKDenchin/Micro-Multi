"""A conversation must call its selected compatible model and save the streamed answer."""

import json

from fastapi.testclient import TestClient

from masp.api import create_app


class FakeStream:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def aiter_lines(self):
        yield "data: " + json.dumps({"choices": [{"delta": {"content": "model reply"}}]})
        yield "data: [DONE]"


class FakeAsyncClient:
    calls = []
    payloads = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def stream(self, method, url, *, headers, json):
        self.calls.append((url, json["model"], json["messages"][-1]["content"]))
        self.payloads.append(json)
        return FakeStream()


def test_chat_uses_selected_model_and_persists_stream(tmp_path, monkeypatch):
    FakeAsyncClient.calls = []
    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        models = []
        for name in ("main-a", "main-b"):
            response = client.post(
                "/api/model-profiles",
                json={
                    "name": name,
                    "base_url": "http://127.0.0.1:9999/v1",
                    "model": name,
                },
            )
            assert response.status_code == 201
            models.append(response.json()["id"])
        for model_id, name in zip(models, ("main-a", "main-b"), strict=True):
            conversation = client.post(
                "/api/conversations", json={"model_profile_id": model_id}
            ).json()
            response = client.post(
                f"/api/conversations/{conversation['id']}/messages",
                json={"content": "hello", "main_only": True},
            )
            assert response.status_code == 200
            assert "model reply" in response.text
            saved = client.get(f"/api/conversations/{conversation['id']}/messages").json()
            saved.sort(key=lambda item: item["created_at"])
            assert [item["role"] for item in saved] == ["user", "assistant"]
            assert saved[-1]["content"] == "model reply"
            assert FakeAsyncClient.calls[-1][1] == name


def test_new_chat_binds_to_selected_project_on_first_message(tmp_path, monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    with TestClient(create_app(tmp_path / "home")) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "main", "model": "main", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        project = client.post("/api/projects", json={"name": "Delayed binding"}).json()
        conversation = client.post(
            "/api/conversations", json={"project_id": None, "model_profile_id": profile["id"]}
        ).json()
        assert conversation["project_id"] is None
        response = client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "start project work", "project_id": project["id"]},
        )
        assert response.status_code == 200
        saved = client.app.state.service.store.get("conversation", conversation["id"])
        assert saved["project_id"] == project["id"]
        assert [
            item["id"]
            for item in client.app.state.service.store.list("conversation", project["id"])
        ] == [conversation["id"]]


def test_switch_model_in_same_conversation_and_include_attachment(tmp_path, monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    with TestClient(create_app(tmp_path / "home")) as client:
        model_ids = [
            client.post(
                "/api/model-profiles",
                json={
                    "name": name,
                    "model": name,
                    "base_url": "http://127.0.0.1:9999/v1",
                },
            ).json()["id"]
            for name in ("alpha", "beta")
        ]
        conversation = client.post(
            "/api/conversations",
            json={
                "model_profile_id": model_ids[0],
            },
        ).json()
        response = client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={
                "content": "read attachment",
                "main_only": True,
                "model_profile_id": model_ids[1],
                "attachments": [{"name": "sample.txt", "content": "attachment evidence"}],
            },
        )
        assert response.status_code == 200
        assert FakeAsyncClient.calls[-1][1] == "beta"
        assert "attachment evidence" in FakeAsyncClient.calls[-1][2]
        messages = client.get(f"/api/conversations/{conversation['id']}/messages").json()
        assert any(item.get("attachments") for item in messages)


def test_read_mode_blocks_unadvertised_write_tool_at_dispatch(tmp_path, monkeypatch):
    class ToolStream(FakeStream):
        async def aiter_lines(self):
            yield "data: " + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "attempted-write",
                                        "type": "function",
                                        "function": {
                                            "name": "write_file",
                                            "arguments": json.dumps(
                                                {
                                                    "path": "forbidden.txt",
                                                    "content": "must not be written",
                                                }
                                            ),
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            )
            yield "data: [DONE]"

    class ToolClient(FakeAsyncClient):
        count = 0

        def stream(self, method, url, *, headers, json):
            self.count += 1
            if self.count == 1:
                names = {tool["function"]["name"] for tool in json["tools"]}
                assert {"write_file", "edit_file", "run_command"} <= names
                return ToolStream()
            assert "未批准" in json["messages"][-1]["content"]
            return FakeStream()

    async def reject_operation(*args, **kwargs):
        return False

    monkeypatch.setattr("masp.permissions.ApprovalBroker.authorize", reject_operation)
    monkeypatch.setattr("httpx.AsyncClient", ToolClient)
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    with TestClient(create_app(tmp_path / "home")) as client:
        project = client.post("/api/projects", json={"name": "permission-test"}).json()
        model = client.post(
            "/api/model-profiles",
            json={
                "name": "test",
                "model": "test",
                "base_url": "http://127.0.0.1:9999/v1",
            },
        ).json()
        conversation = client.post(
            "/api/conversations",
            json={
                "project_id": project["id"],
                "model_profile_id": model["id"],
            },
        ).json()
        response = client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={
                "content": "read project",
                "access_mode": "read",
            },
        )
        assert response.status_code == 200
        from pathlib import Path

        assert not (Path(project["repository"]) / "forbidden.txt").exists()
