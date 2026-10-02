"""The real-team API should bind each coding task to its configured model."""

import sys

import pytest
from fastapi.testclient import TestClient

from masp.api import create_app


class FakeResponse:
    status_code = 200

    def __init__(self, data: dict[str, object], model: str):
        self.data = data
        self.model = model

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        import json

        return {
            "choices": [{"message": {"content": json.dumps(self.data)}}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 20},
        }


def fake_completion(url, *, headers, timeout, json):
    model = json["model"]
    user = __import__("json").loads(json["messages"][-1]["content"])
    if "files" in user:
        return FakeResponse({"findings": []}, model)
    if "policy" in user:

        def checks(name):
            return [
                {
                    "name": f"compile-{name}",
                    "layer": "build",
                    "command": [sys.executable, "-m", "py_compile", f"{name}.py"],
                },
                {
                    "name": f"unit-{name}",
                    "layer": "unit",
                    "command": [
                        sys.executable,
                        "-c",
                        f"import {name}; assert {name}.value() == {1 if name == 'a' else 2}",
                    ],
                },
            ]

        return FakeResponse(
            {
                "project": {"name": "Two agents"},
                "architecture": {"modules": ["a.py", "b.py"]},
                "contracts": [{"type": "interface", "signatures": ["a.value", "b.value"]}],
                "tasks": [
                    {
                        "id": name,
                        "title": name,
                        "description": f"Implement {name}.value",
                        "agent_id": f"{name}_agent",
                        "module": f"{name}.py",
                        "allowed_paths": [f"{name}.py"],
                        "acceptance_criteria": ["returns value"],
                        "checks": checks(name),
                    }
                    for name in ("a", "b")
                ],
                "final_checks": [
                    {
                        "name": "integrated",
                        "layer": "integration",
                        "command": [
                            sys.executable,
                            "-c",
                            "import a,b; assert a.value() + b.value() == 3",
                        ],
                    }
                ],
            },
            model,
        )
    name = user["task"]["id"]
    return FakeResponse(
        {
            "summary": f"Implemented {name}",
            "files": {f"{name}.py": f"def value():\n    return {1 if name == 'a' else 2}\n"},
        },
        model,
    )


@pytest.mark.parametrize("review_mode", ["adaptive", "internal", "open-code-review"])
def test_team_models_and_local_parallel_run(tmp_path, monkeypatch, review_mode):
    monkeypatch.setattr("masp.agents.httpx.post", fake_completion)
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    monkeypatch.setattr(
        "masp.service.run_open_code_review",
        lambda workspace, config: (
            [],
            {"engine": "open-code-review", "status": "success", "model": config.model},
        ),
    )
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Real flow", "provider": "openai-compatible"},
        ).json()
        profile_ids = []
        for name in ("main", "a", "b"):
            response = client.post(
                "/api/model-profiles",
                json={
                    "name": name,
                    "base_url": "http://127.0.0.1:9999/v1",
                    "model": name,
                },
            )
            assert response.status_code == 201, response.text
            assert "api_key" not in response.json()
            profile_ids.append(response.json()["id"])
        team = client.put(
            f"/api/projects/{project['id']}/team",
            json={
                "requirement": "Create two Python modules",
                "main_profile_id": profile_ids[0],
                "review_profile_id": profile_ids[0],
                "review_mode": review_mode,
                "agents": [
                    {
                        "id": "a_agent",
                        "name": "A",
                        "responsibility": "Implement a",
                        "model_profile_id": profile_ids[1],
                    },
                    {
                        "id": "b_agent",
                        "name": "B",
                        "responsibility": "Implement b",
                        "model_profile_id": profile_ids[2],
                    },
                ],
                "max_concurrency": 2,
            },
        )
        assert team.status_code == 200, team.text
        assert client.post(f"/api/projects/{project['id']}/team/start", json={}).status_code == 409
        assert (
            client.post(f"/api/projects/{project['id']}/team/approve", json={}).status_code == 200
        )
        run = client.post(
            f"/api/projects/{project['id']}/team/start",
            json={"execution_mode": "local"},
        )
        assert run.status_code == 202, run.text
        run_id = run.json()["id"]
        app.state.service.futures[run_id].result(timeout=60)
        snapshot = client.get(f"/api/runs/{run_id}").json()
        assert snapshot["state"] == "SUCCEEDED", [
            (task["error"], task["attempts"]) for task in snapshot["tasks"]
        ]
        assert {task["spec"]["agent_id"] for task in snapshot["tasks"]} == {
            "a_agent",
            "b_agent",
        }
        assert {(agent["role"], agent["model"]) for agent in snapshot["agents"]} >= {
            ("planner", "main"),
            ("a_agent", "a"),
            ("b_agent", "b"),
        }
        event_types = {item["type"] for item in client.get(f"/api/runs/{run_id}/events").json()}
        assert ("review.external" in event_types) == (review_mode == "open-code-review")
        assert ("review.unified" in event_types) == (review_mode == "internal")
        if review_mode == "adaptive":
            assert not any(agent["role"] == "reviewer" for agent in snapshot["agents"])
        followup = client.post(
            f"/api/projects/{project['id']}/team/start",
            json={
                "requirement": "Refine module a while keeping b working",
                "execution_mode": "local",
            },
        )
        assert followup.status_code == 202, followup.text
        next_run = followup.json()
        assert next_run["previous_run_id"] == run_id
        app.state.service.futures[next_run["id"]].result(timeout=60)
        assert client.get(f"/api/runs/{next_run['id']}").json()["previous_run_id"] == run_id
