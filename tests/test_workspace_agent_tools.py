import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from masp.api import create_app
from masp.chat_tools import list_workspace_files, run_chat_tool
from masp.domain import TaskSpec
from masp.workspace import collect_tool_edits, git, init_repo


def test_exact_edit_rejects_ambiguity_and_enforces_agent_scope(tmp_path):
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    arguments = json.dumps({"path": "app.py", "old_text": "1", "new_text": "2"})
    denied = run_chat_tool(tmp_path, "edit_file", arguments, allowed_paths=["other.py"])
    assert "范围" in denied
    assert "1" in (tmp_path / "app.py").read_text()
    assert "written" in run_chat_tool(tmp_path, "edit_file", arguments, allowed_paths=["app.py"])
    assert (tmp_path / "app.py").read_text() == "value = 2\n"
    repeated = json.dumps({"path": "app.py", "old_text": "missing", "new_text": "x"})
    assert "恰好出现一次" in run_chat_tool(tmp_path, "edit_file", repeated)


def test_real_tool_changes_are_collected_and_cannot_escape_review_scope(tmp_path):
    root = tmp_path / "repo"
    init_repo(root)
    revision = git(root, "rev-parse", "HEAD")
    task = TaskSpec.model_validate(
        {
            "id": "app",
            "title": "app",
            "description": "Implement app",
            "module": "app.py",
            "allowed_paths": ["app.py"],
            "acceptance_criteria": ["works"],
            "checks": [
                {"name": "build", "layer": "build", "command": ["python", "app.py"]},
                {"name": "unit", "layer": "unit", "command": ["python", "app.py"]},
            ],
        }
    )
    (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
    assert collect_tool_edits(root, task, revision) == {"app.py": "print('ok')\n"}
    (root / "outside.py").write_text("print('unexpected')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside task scope"):
        collect_tool_edits(root, task, revision)


def test_agent_can_write_read_and_run_project_commands(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    (root / "README.md").write_text("# Workspace\n", encoding="utf-8")

    written = json.loads(
        run_chat_tool(
            root, "write_file", json.dumps({"path": "src/main.py", "content": "print('ok')\n"})
        )
    )
    assert written["written"] == "src/main.py"
    assert run_chat_tool(root, "read_file", json.dumps({"path": "src/main.py"})) == "print('ok')\n"

    command = json.loads(
        run_chat_tool(root, "run_command", json.dumps({"command": "python -c \"print('ok')\""}))
    )
    assert command["exit_code"] == 0
    assert "ok" in command["stdout"]
    assert any(
        item["path"] == "src" and item["type"] == "directory" for item in list_workspace_files(root)
    )


def test_agent_tools_refuse_paths_outside_project_and_shell_chains(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    outside = tmp_path / "outside.txt"

    result = run_chat_tool(
        root, "write_file", json.dumps({"path": "../outside.txt", "content": "x"})
    )
    assert not result.startswith("{")
    assert not outside.exists()

    result = run_chat_tool(
        root, "run_command", json.dumps({"command": "python --version && whoami"})
    )
    assert not result.startswith("{")


def test_workspace_browser_hides_credential_files(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    (root / "app.py").write_text("print(1)", encoding="utf-8")
    (root / ".env.local").write_text("API_KEY=private", encoding="utf-8")
    (root / "private.pem").write_text("private", encoding="utf-8")

    assert [item["name"] for item in list_workspace_files(root)] == ["app.py"]


def test_linked_local_project_exposes_workspace_and_command_tools(tmp_path):
    source = tmp_path / "local-project"
    source.mkdir()
    (source / "README.md").write_text("# Local files\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
        ],
        check=True,
        capture_output=True,
    )

    app = create_app(tmp_path / "masp-home")
    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "local", "repository": str(source), "link_repository": True},
        )
        assert project.status_code == 201
        project_id = project.json()["id"]
        assert (
            client.get(f"/api/projects/{project_id}/workspace/files").json()[0]["name"]
            == "README.md"
        )
        assert (
            client.get(
                f"/api/projects/{project_id}/workspace/file", params={"path": "README.md"}
            ).json()["content"]
            == "# Local files\n"
        )
        command = client.post(
            f"/api/projects/{project_id}/workspace/command", json={"command": "git status --short"}
        )
        assert command.status_code == 200
        assert command.json()["exit_code"] == 0
