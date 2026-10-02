"""Skills are discoverable and loaded only when selected by an agent."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from masp.api import create_app
from masp.chat_tools import run_chat_tool


def test_skill_catalog_and_on_demand_content(tmp_path):
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        project = client.post(
            "/api/projects", json={"name": "Skills project", "provider": "openai-compatible"}
        ).json()
        root = Path(project["repository"])
        response = client.post(
            "/api/skills",
            json={
                "name": "review-guidance",
                "content": "---\ndescription: Review changed code carefully\n---\nCheck tests.",
            },
        )
        assert response.status_code == 201
        skill_folder = root / ".agents" / "skills" / "project-skill"
        skill_folder.mkdir(parents=True)
        (skill_folder / "SKILL.md").write_text(
            "---\ndescription: Build a local project\n---\nRun checks.", encoding="utf-8"
        )
        listed = client.get(f"/api/skills?project_id={project['id']}").json()
        assert {item["name"] for item in listed} == {"review-guidance", "project-skill"}
        loaded = run_chat_tool(
            root,
            "load_skill",
            json.dumps({"name": "project-skill"}),
            app.state.service.home,
        )
        assert "Run checks." in loaded
        assert "Invalid skill name" in run_chat_tool(
            root, "load_skill", json.dumps({"name": "../escape"}), app.state.service.home
        )
