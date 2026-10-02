from fastapi.testclient import TestClient

from masp.api import create_app


def test_delete_and_restore_preserves_messages_and_other_conversations(tmp_path):
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        first = client.post("/api/conversations", json={"title": "first"}).json()
        second = client.post("/api/conversations", json={"title": "second"}).json()
        app.state.service.store.put(
            "message",
            {
                "id": "saved-message",
                "role": "user",
                "content": "keep this",
            },
            first["id"],
        )
        response = client.delete(
            f"/api/conversations/{first['id']}",
            headers={
                "content-type": "application/json",
            },
        )
        assert response.status_code == 204
        assert [c["id"] for c in client.get("/api/conversations").json()] == [second["id"]]
        assert (
            client.post(
                f"/api/conversations/{first['id']}/messages",
                json={
                    "content": "cannot continue deleted chat",
                },
            ).status_code
            == 404
        )
        assert client.post(f"/api/conversations/{first['id']}/restore", json={}).status_code == 200
        assert len(client.get("/api/conversations").json()) == 2
        assert (
            client.get(f"/api/conversations/{first['id']}/messages").json()[0]["content"]
            == "keep this"
        )


def test_unknown_conversation_cannot_be_deleted(tmp_path):
    with TestClient(create_app(tmp_path / "home")) as client:
        assert (
            client.delete(
                "/api/conversations/missing",
                headers={
                    "content-type": "application/json",
                },
            ).status_code
            == 404
        )
