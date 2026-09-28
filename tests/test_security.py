import pytest

from masp.agents import Budget, CompatibleProvider, ModelError, fixture_plan
from masp.domain import Check, Proposal
from masp.verification import DockerTool, FixtureTool
from masp.workspace import apply_proposal, target


def test_proposal_write_scope_checked_before_any_file_is_written(tmp_path):
    task = fixture_plan().tasks[0]
    proposal = Proposal(summary="bad", files={"calculator/add.py": "ok", "unrelated.py": "bad"})
    with pytest.raises(ValueError, match="outside task scope"):
        apply_proposal(tmp_path, task, proposal)
    assert not list(tmp_path.iterdir())


def test_docker_is_fail_closed_without_executable(tmp_path, monkeypatch):
    monkeypatch.setattr("masp.verification.shutil.which", lambda _: None)
    check = Check(name="unit", layer="unit", command=["python", "-m", "unittest"])
    result = DockerTool().execute(tmp_path, check, lambda: False)
    assert result.status == "failed"
    assert result.error_type == "SECURITY_BLOCK"


def test_docker_configuration_isolated_and_read_only(tmp_path):
    check = Check(name="unit", layer="unit", command=["python", "-m", "unittest"])
    command = DockerTool().command(tmp_path, "test", check)
    assert {
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--pids-limit=128",
        "--memory=512m",
        "--cpus=1",
        "--user=65534:65534",
    } <= set(command)
    assert any("target=/workspace,readonly" in part for part in command)
    assert not any("docker.sock" in part for part in command)


def test_fixture_refuses_arbitrary_shell(tmp_path):
    result = FixtureTool().execute(
        tmp_path,
        Check(name="bad", layer="unit", command=["python", "-c", "print('bad')"]),
        lambda: False,
    )
    assert result.status == "failed"


def test_fixture_never_executes_generated_code(tmp_path):
    folder = tmp_path / "calculator"
    folder.mkdir()
    (folder / "add.py").write_text("import os\nos.system('echo SHOULD_NOT_RUN')\n")
    result = FixtureTool().execute(
        tmp_path, Check(name="bad", layer="unit", command=["fixture", "add"]), lambda: False
    )
    assert result.status == "failed"
    assert "one arithmetic function" in result.stderr


def test_link_escape_rejected(tmp_path):
    link = tmp_path / "linked"
    try:
        link.symlink_to(tmp_path.parent, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not grant symlink creation")
    with pytest.raises(ValueError, match="linked"):
        target(tmp_path, "linked/file.py")


def test_model_requires_explicit_configuration(monkeypatch):
    monkeypatch.delenv("MASP_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("MASP_MODEL_NAME", raising=False)
    with pytest.raises(ModelError, match="Configure"):
        CompatibleProvider().generate("planner", {}, {}, 1000)


def test_model_budget_admission_before_network():
    with pytest.raises(ModelError, match="RESOURCE_ERROR"):
        Budget(1000).call(CompatibleProvider(), "planner", {}, {})
