import pytest
from pydantic import ValidationError

from masp.agents import fixture_plan
from masp.contracts import conflicts, ready
from masp.domain import Plan, Proposal, RunCreate, State, check_transition, safe_path


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/root",
        "D:/escape",
        "a\\b",
        ".git/config",
        "A/.GIT/config",
        "a/../b",
        "con.txt",
        "a.",
        "foo:bar",
        "a//b",
    ],
)
def test_path_escape_rejected(name):
    with pytest.raises(ValueError):
        safe_path(name)


def test_plan_rejects_cycles_duplicates_unknown_dependencies():
    for mode in ("cycle", "duplicate", "missing"):
        raw = fixture_plan().model_dump()
        if mode == "cycle":
            raw["tasks"][0]["dependencies"] = ["subtract"]
            raw["tasks"][1]["dependencies"] = ["add"]
        elif mode == "duplicate":
            raw["tasks"][1]["id"] = "add"
        else:
            raw["tasks"][0]["dependencies"] = ["missing"]
        with pytest.raises(ValidationError):
            Plan.model_validate(raw)


def test_mandatory_checks_and_unknown_fields():
    raw = fixture_plan().model_dump()
    raw["tasks"][0]["checks"] = raw["tasks"][0]["checks"][:1]
    with pytest.raises(ValidationError, match="build and unit"):
        Plan.model_validate(raw)
    with pytest.raises(ValidationError):
        RunCreate.model_validate({"requirement": "Make an app", "max_agents": 100})
    with pytest.raises(ValidationError):
        RunCreate.model_validate({"requirement": "Make an app", "arbitrary": True})


def test_scheduler_obeys_dependencies_resources_priority():
    a, b = fixture_plan().tasks
    states = {"add": "QUEUED", "subtract": "QUEUED"}
    assert len(ready([a, b], states, [], 2)) == 2
    b.dependencies = ["add"]
    assert ready([a, b], states, [], 2) == [a]
    states["add"] = "SUCCEEDED"
    assert ready([a, b], states, [], 2) == [b]
    b.dependencies = []
    a.resources = b.resources = ["database"]
    assert conflicts(a, b)
    assert not ready([b], states, [a], 2)
    a.resources = b.resources = []
    b.allowed_paths = ["CALCULATOR"]
    assert conflicts(a, b)


def test_terminal_state_cannot_be_reopened_or_skip_gate():
    with pytest.raises(ValueError):
        check_transition("SUCCEEDED", State.RUNNING)
    with pytest.raises(ValueError):
        check_transition("RUNNING", State.SUCCEEDED)
    check_transition("VERIFYING", State.REPAIRING)


def test_proposal_rejects_case_aliases_and_large_writes():
    with pytest.raises(ValidationError):
        Proposal(summary="bad", files={"Foo.py": "a", "foo.py": "b"})
    with pytest.raises(ValidationError):
        Proposal(summary="bad", files={"a.py": "a" * 2_000_001})
