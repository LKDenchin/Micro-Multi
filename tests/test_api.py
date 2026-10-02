import pytest
from fastapi.testclient import TestClient

from masp.agents import fixture_plan
from masp.api import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "api")
    with TestClient(app) as client:
        yield client


def test_web_assets_and_openapi(client):
    assert client.get("/").status_code == 200
    assert 'id="composer"' in client.get("/").text
    assert client.get("/static/chat.js").status_code == 200
    assert client.get("/workspace").status_code == 404
    assert "/api/projects" in client.get("/openapi.json").json()["paths"]
    assert client.get("/api/health").json()["status"] == "ok"


def test_api_create_run_replay_trace_and_download(client):
    project = client.post("/api/projects", json={"name": "API project"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/runs",
        json={"requirement": "Create arithmetic functions", "inject_failure": True},
    )
    assert response.status_code == 202
    run = response.json()
    client.app.state.service.futures[run["id"]].result(timeout=60)
    replay = client.get(f"/api/runs/{run['id']}/replay").json()
    assert replay["state"] == "SUCCEEDED"
    assert len(replay["tasks"]) == 2
    events = client.get(f"/api/runs/{run['id']}/events").json()
    assert events[-1]["type"] == "run.completed"
    stream = client.get(f"/api/runs/{run['id']}/stream").text
    assert "event: complete" in stream
    assert "repair.started" in stream
    response = client.get(f"/api/artifacts/{replay['artifact_id']}/download")
    assert response.status_code == 200
    assert response.content[:2] == b"PK"
    assert len(client.get(f"/api/projects/{project['id']}/contracts").json()) == 1


def test_bad_input_missing_resources_and_cross_origin_writes(client):
    assert client.post("/api/projects", json={"name": "../evil"}).status_code == 422
    assert client.get("/api/runs/missing").status_code == 404
    assert (
        client.post(
            "/api/projects", json={"name": "evil"}, headers={"Origin": "https://attacker.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/projects", content='{"name":"evil"}', headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    assert client.get("/api/health", headers={"Host": "evil.invalid"}).status_code == 400


def test_contract_schema_endpoint(client):
    response = client.post("/api/contracts/check", json=fixture_plan().model_dump())
    assert response.status_code == 200
    assert response.json()["status"] == "passed"
