from fastapi.testclient import TestClient

from masp.api import create_app
from masp.domain import RunCreate, TeamInput
from masp.workspace import git


def test_import_plain_folder_initializes_git_and_excludes_secrets(tmp_path):
    source = tmp_path / "plain-folder"
    source.mkdir()
    (source / "app.py").write_text("print('ok')", encoding="utf-8")
    (source / ".env").write_text("SECRET=do-not-copy-to-git", encoding="utf-8")
    with TestClient(create_app(tmp_path / "home")) as client:
        response = client.post(
            "/api/projects", json={"name": "Plain folder", "repository": str(source)}
        )
        assert response.status_code == 201
        root = __import__("pathlib").Path(response.json()["repository"])
        assert git(root, "branch", "--show-current") == "main"
        assert (root / "app.py").read_text(encoding="utf-8") == "print('ok')"
        assert not (root / ".env").exists()
        assert git(root, "status", "--short") == ""
        assert not (source / ".git").exists()


def test_plain_folder_can_be_linked_and_gets_initial_branch(tmp_path):
    source = tmp_path / "linked-folder"
    source.mkdir()
    (source / "readme.md").write_text("work", encoding="utf-8")
    with TestClient(create_app(tmp_path / "home")) as client:
        response = client.post(
            "/api/projects",
            json={"name": "Linked folder", "repository": str(source), "link_repository": True},
        )
    assert response.status_code == 201
    assert response.json()["repository"] == str(source)
    assert git(source, "branch", "--show-current") == "main"


def test_project_search_matches_message_content_and_custom_parallel_limit(tmp_path):
    with TestClient(create_app(tmp_path / "home")) as client:
        conversation = client.post("/api/conversations", json={"title": "Build help"}).json()
        app_store = client.app.state.service.store
        app_store.put(
            "message",
            {"id": "search-message", "role": "user", "content": "unique needle in body"},
            conversation["id"],
        )
        app_store.update("conversation", conversation["id"], message_count=1)
        found = client.get("/api/search", params={"q": "unique needle"}).json()
        assert found[0]["id"] == conversation["id"]
        assert found[0]["match"] == "content"
    assert RunCreate(requirement="valid request", max_agents=12).max_agents == 12
    assert TeamInput.model_fields["max_concurrency"].annotation


def test_global_search_finds_project_files_and_settings(tmp_path):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "needle.py").write_text("print('searchable')", encoding="utf-8")
    with TestClient(create_app(tmp_path / "home")) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Search Project", "repository": str(source), "link_repository": True},
        ).json()
        client.post("/api/conversations", json={"title": "New Chat Draft"})
        result = client.get("/api/search/global", params={"q": "search"}).json()
        assert any(item["id"] == project["id"] for item in result["projects"])
        assert any(item["path"] == "needle.py" for item in result["files"])
        assert any(
            item["section"] == "workspace"
            for item in client.get("/api/search/global", params={"q": "workspace"}).json()[
                "settings"
            ]
        )
        assert client.get("/api/search/global", params={"q": "draft"}).json()["chats"] == []


def test_project_branch_picker_lists_and_switches_clean_branches(tmp_path):
    source = tmp_path / "branch-repo"
    source.mkdir()
    (source / "README.md").write_text("repo", encoding="utf-8")
    with TestClient(create_app(tmp_path / "home")) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Branch Project", "repository": str(source), "link_repository": True},
        ).json()
        project_id = project["id"]
        assert (
            client.post(
                f"/api/projects/{project_id}/branches", json={"name": "feature/new", "create": True}
            ).status_code
            == 200
        )
        assert git(source, "branch", "--show-current") == "feature/new"
        (source / "dirty.txt").write_text("uncommitted", encoding="utf-8")
        blocked = client.post(f"/api/projects/{project_id}/branches", json={"name": "main"})
        assert blocked.status_code == 409
