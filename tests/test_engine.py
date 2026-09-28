import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from masp.agents import FixtureProvider, Generation, fixture_plan
from masp.domain import CheckResult, ProjectCreate, RunCreate
from masp.service import Service
from masp.verification import FixtureTool
from masp.workspace import git


def execute(service, **kwargs):
    project = service.create_project(ProjectCreate(name="test"))
    run = service.start_run(
        project["id"], RunCreate(requirement="Build arithmetic modules", **kwargs)
    )
    service.futures[run["id"]].result(timeout=60)
    return project, service.snapshot(run["id"])


def test_e2e_fault_repair_merge_and_real_artifact_tests(service):
    project, run = execute(service, inject_failure=True)
    assert run["state"] == "SUCCEEDED", run
    assert run["metrics"]["repair_count"] == 1
    tasks = {task["spec_id"]: task for task in run["tasks"]}
    assert tasks["subtract"]["attempts"][0]["checks"][-1]["status"] == "failed"
    assert tasks["subtract"]["attempts"][1]["checks"][-1]["status"] == "passed"
    assert len({task["workspace"] for task in tasks.values()}) == 2
    assert all(task["commit"] and task["diff"] for task in tasks.values())
    events = service.store.events(run["id"])
    types = {event["type"] for event in events}
    assert {"repair.started", "repair.completed", "merge.completed", "run.completed"} <= types
    assert len({event["sequence"] for event in events}) == len(events)
    assert git(Path(project["repository"]), "rev-parse", "HEAD") == run["commit"]
    artifact = service.store.get("artifact", run["artifact_id"])
    with zipfile.ZipFile(artifact["path"]) as archive:
        assert {"calculator/add.py", "calculator/subtract.py", "tests/test_add.py"} <= set(
            archive.namelist()
        )
        assert not any(".git/" in name for name in archive.namelist())
    # Test-owned, fixed source fixture: execute the generated unittest suite independently.
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=project["repository"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "Ran 2 tests" in result.stderr


def test_retry_exhaustion_does_not_merge_project(service):
    project, run = execute(service, inject_failure=True, max_retries=0)
    assert run["state"] == "HUMAN_REVIEW_REQUIRED"
    assert run["artifact_id"] is None
    assert git(Path(project["repository"]), "rev-parse", "HEAD") == run["repository_revision"]
    assert any(task["state"] == "HUMAN_REVIEW_REQUIRED" for task in run["tasks"])


def test_final_gate_failure_prevents_publication(service, monkeypatch):
    original = FixtureTool.execute

    def fail_final(self, root, check, stop):
        if check.layer == "integration":
            return CheckResult(
                name=check.name,
                layer=check.layer,
                command=check.command,
                status="failed",
                exit_code=1,
                duration_ms=1,
                stderr="injected",
            )
        return original(self, root, check, stop)

    monkeypatch.setattr(FixtureTool, "execute", fail_final)
    project, run = execute(service)
    assert run["state"] == "FAILED"
    assert run["artifact_id"] is None
    assert git(Path(project["repository"]), "rev-parse", "HEAD") == run["repository_revision"]


def test_two_coders_actually_overlap(service, monkeypatch):
    barrier = threading.Barrier(2)
    entered = []
    original = FixtureProvider.generate

    def synchronized(self, role, payload, schema, max_tokens):
        if role == "coder":
            entered.append(payload["task"]["id"])
            barrier.wait(timeout=15)
        return original(self, role, payload, schema, max_tokens)

    monkeypatch.setattr(FixtureProvider, "generate", synchronized)
    _, run = execute(service)
    assert run["state"] == "SUCCEEDED", run
    assert sorted(entered) == ["add", "subtract"]


def test_failed_dependency_is_blocked(service, monkeypatch):
    original = FixtureProvider.generate

    def chained(self, role, payload, schema, max_tokens):
        if role == "planner":
            plan = fixture_plan()
            plan.tasks[0].dependencies = ["subtract"]
            return Generation(plan.model_dump(), "fixture", 0, 0, 0)
        return original(self, role, payload, schema, max_tokens)

    monkeypatch.setattr(FixtureProvider, "generate", chained)
    _, run = execute(service, inject_failure=True, max_retries=0)
    assert next(t for t in run["tasks"] if t["spec_id"] == "add")["state"] == "BLOCKED"


def test_cancel_during_planning_and_no_duplicate_run(service, monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = FixtureProvider.generate

    def waiting(self, role, payload, schema, max_tokens):
        if role == "planner":
            started.set()
            release.wait(10)
        return original(self, role, payload, schema, max_tokens)

    monkeypatch.setattr(FixtureProvider, "generate", waiting)
    project = service.create_project(ProjectCreate(name="Cancel"))
    request = RunCreate(requirement="Build arithmetic")
    run = service.start_run(project["id"], request)
    assert started.wait(10)
    with pytest.raises(ValueError, match="already active"):
        service.start_run(project["id"], request)
    service.control(run["id"], "pause")
    assert service.snapshot(run["id"])["display_state"] == "PAUSED"
    service.control(run["id"], "resume")
    service.control(run["id"], "cancel")
    release.set()
    service.futures[run["id"]].result(timeout=20)
    result = service.snapshot(run["id"])
    assert result["state"] == "CANCELLED"
    assert result["artifact_id"] is None


def test_runtime_deadline_cannot_produce_success(service, monkeypatch):
    original = FixtureProvider.generate

    def slow(self, role, payload, schema, max_tokens):
        if role == "planner":
            time.sleep(1.1)
        return original(self, role, payload, schema, max_tokens)

    monkeypatch.setattr(FixtureProvider, "generate", slow)
    _, run = execute(service, max_runtime=1)
    assert run["state"] == "FAILED"
    assert run["error"] == "TIMEOUT"


def test_import_preserves_source_and_uses_committed_state(service, tmp_path):
    first = service.create_project(ProjectCreate(name="source"))
    source = Path(first["repository"])
    (source / "uncommitted.txt").write_text("private unfinished work")
    before = git(source, "rev-parse", "HEAD")
    imported = service.create_project(ProjectCreate(name="imported", repository=str(source)))
    assert git(Path(imported["repository"]), "rev-parse", "HEAD") == before
    assert not (Path(imported["repository"]) / "uncommitted.txt").exists()
    assert (source / "uncommitted.txt").read_text() == "private unfinished work"


def test_contract_change_is_blocked_until_explicit_recorded_approval(service, monkeypatch):
    project = service.create_project(ProjectCreate(name="contract"))
    first = service.start_run(project["id"], RunCreate(requirement="Build arithmetic"))
    service.futures[first["id"]].result(timeout=60)
    assert service.snapshot(first["id"])["state"] == "SUCCEEDED"
    from masp.agents import FixtureProvider

    original = FixtureProvider.generate

    def changed_plan(self, role, payload, schema, max_tokens):
        result = original(self, role, payload, schema, max_tokens)
        if role == "planner":
            result.data["contracts"][0]["acceptance"] = "only integers"
        return result

    monkeypatch.setattr(FixtureProvider, "generate", changed_plan)
    blocked = service.start_run(project["id"], RunCreate(requirement="Change arithmetic API"))
    service.futures[blocked["id"]].result(timeout=30)
    blocked = service.snapshot(blocked["id"])
    assert blocked["state"] == "HUMAN_REVIEW_REQUIRED"
    assert blocked["contract_id"]
    contract = service.store.get("contract", blocked["contract_id"])
    assert contract["potentially_breaking"]
    assert blocked["error"].startswith("CONTRACT_ERROR")

    approved = service.start_run(
        project["id"], RunCreate(requirement="Change arithmetic API", approve_contract_change=True)
    )
    service.futures[approved["id"]].result(timeout=60)
    result = service.snapshot(approved["id"])
    assert result["state"] == "SUCCEEDED", result["error"]
    assert any(
        event["type"] == "human.contract_override" for event in service.store.events(result["id"])
    )


def test_recover_interrupted_run_never_reports_success(tmp_path):
    first = Service(tmp_path / "home")
    first.store.put("run", {"id": "interrupted", "state": "RUNNING"})
    first.close()
    second = Service(tmp_path / "home")
    try:
        assert second.store.get("run", "interrupted")["state"] == "HUMAN_REVIEW_REQUIRED"
        assert second.store.events("interrupted")[-1]["type"] == "run.interrupted"
    finally:
        second.close()
