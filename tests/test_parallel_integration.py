from pathlib import Path

import pytest

from masp.agents import FixtureProvider, Generation, fixture_plan
from masp.domain import CheckResult, ProjectCreate, RunCreate
from masp.workspace import GitError, Workspace, git, init_repo


def test_conflicting_parallel_changes_do_not_silently_overwrite(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / "shared.txt").write_text("original\n")
    git(repo, "add", "shared.txt")
    git(repo, "commit", "-m", "initial shared file")
    manager = Workspace(repo, tmp_path / "run", "conflict", git(repo, "rev-parse", "HEAD"))
    manager.create()
    first, second = manager.task("first"), manager.task("second")
    (first / "shared.txt").write_text("first\n")
    (second / "shared.txt").write_text("second\n")
    manager.merge(manager.commit(first, "first"))
    with pytest.raises(GitError):
        manager.merge(manager.commit(second, "second"))
    assert (manager.integration / "shared.txt").read_text() == "first\n"
    assert (repo / "shared.txt").read_text() == "original\n"
    assert git(manager.integration, "status", "--porcelain") == ""


def test_external_review_mode_does_not_bypass_failed_checks(service, monkeypatch):
    class Provider:
        def __init__(self, *args, **kwargs):
            pass

        def generate(self, role, payload, schema, max_tokens):
            if role == "planner":
                plan = fixture_plan()
                plan.tasks = [plan.tasks[0]]
                plan.tasks[0].agent_id = "worker"
                return Generation(plan.model_dump(), "fixture", 0, 0, 0)
            return FixtureProvider().generate(role, payload, schema, max_tokens)

    def failed(self, root, check, stop):
        return CheckResult(
            name=check.name,
            layer=check.layer,
            status="failed",
            command=check.command,
            exit_code=1,
            duration_ms=1,
        )

    monkeypatch.setattr("masp.service.CompatibleProvider", Provider)
    monkeypatch.setenv("MASP_MODEL_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("MASP_MODEL_NAME", "fixture")
    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    monkeypatch.setattr("masp.service.LocalTool.execute", failed)
    monkeypatch.setattr(
        "masp.service.run_open_code_review", lambda *args: ([], {"status": "success"})
    )
    project = service.create_project(
        ProjectCreate(name="Failed checks", provider="openai-compatible")
    )
    root = Path(project["repository"])
    revision = git(root, "rev-parse", "HEAD")
    run = service.start_run(
        project["id"],
        RunCreate(requirement="Implement arithmetic", execution_mode="local", max_retries=0),
        team={
            "main_profile_id": "env-default",
            "review_mode": "open-code-review",
            "agents": [
                {
                    "id": "worker",
                    "name": "worker",
                    "model_profile_id": "env-default",
                    "owned_paths": [],
                }
            ],
        },
    )
    service.futures[run["id"]].result(timeout=60)
    snapshot = service.snapshot(run["id"])
    assert snapshot["state"] == "HUMAN_REVIEW_REQUIRED", snapshot.get("error")
    assert snapshot["artifact_id"] is None
    assert git(root, "rev-parse", "HEAD") == revision
