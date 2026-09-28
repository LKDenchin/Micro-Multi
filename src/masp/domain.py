"""Canonical v1 API and agent contract. All external inputs are validated here."""

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class State(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    CONTRACTING = "CONTRACTING"
    SCHEDULING = "SCHEDULING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    REVIEWING = "REVIEWING"
    VERIFYING = "VERIFYING"
    REPAIRING = "REPAIRING"
    INTEGRATING = "INTEGRATING"
    FINAL_VERIFY = "FINAL_VERIFY"
    PAUSED = "PAUSED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


TERMINAL = {
    State.SUCCEEDED,
    State.FAILED,
    State.BLOCKED,
    State.CANCELLED,
    State.HUMAN_REVIEW_REQUIRED,
}
EDGES: dict[State, set[State]] = {
    State.CREATED: {State.PLANNING, State.QUEUED},
    State.PLANNING: {State.CONTRACTING},
    State.CONTRACTING: {State.SCHEDULING},
    State.SCHEDULING: {State.RUNNING},
    State.QUEUED: {State.RUNNING, State.BLOCKED},
    State.RUNNING: {State.REVIEWING, State.INTEGRATING, State.REPAIRING},
    State.REVIEWING: {State.VERIFYING, State.REPAIRING},
    State.VERIFYING: {State.REPAIRING, State.INTEGRATING},
    State.REPAIRING: {State.RUNNING},
    State.INTEGRATING: {State.SUCCEEDED, State.FINAL_VERIFY},
    State.FINAL_VERIFY: {State.SUCCEEDED},
}


def check_transition(before: str, after: State) -> None:
    old = State(before)
    if old in TERMINAL or (
        after not in EDGES.get(old, set())
        and after
        not in {
            State.FAILED,
            State.CANCELLED,
            State.HUMAN_REVIEW_REQUIRED,
        }
    ):
        raise ValueError(f"Invalid transition: {old} -> {after}")


def safe_path(value: str) -> str:
    parts = value.split("/")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if (
        not value
        or len(value) > 200
        or any(
            part in {"", ".", ".."}
            or part.lower() in {".git", ".masp"}
            or part.endswith((".", " "))
            or part.split(".")[0].lower() in reserved
            or re.search(r'[<>:"\\|?*\x00-\x1f]', part)
            for part in parts
        )
    ):
        raise ValueError(f"Unsafe relative path: {value!r}")
    return value


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[\w .-]+$")
    description: str = Field(default="", max_length=4000)
    repository: str | None = Field(default=None, max_length=1000)
    language: Literal["python"] = "python"
    provider: Literal["fixture", "openai-compatible"] = "fixture"


class RunCreate(StrictModel):
    requirement: str = Field(min_length=5, max_length=16000)
    max_agents: int = Field(default=2, ge=1, le=4)
    max_retries: int = Field(default=3, ge=0, le=5)
    max_runtime: int = Field(default=600, ge=1, le=3600)
    max_tokens: int = Field(default=200000, ge=1000, le=1000000)
    inject_failure: bool = False
    approve_contract_change: bool = False


class Check(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    layer: Literal["contract", "build", "lint", "type", "unit", "integration", "security"]
    command: list[str] = Field(min_length=1, max_length=30)
    timeout: int = Field(default=60, ge=1, le=120)

    @field_validator("command")
    @classmethod
    def arguments(cls, values: list[str]) -> list[str]:
        if any(not value or "\x00" in value or len(value) > 16000 for value in values):
            raise ValueError("Invalid command argument")
        return values


class TaskSpec(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,40}$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=8000)
    module: str
    dependencies: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(min_length=1, max_length=30)
    resources: list[str] = Field(default_factory=list)
    priority: int = Field(default=0, ge=0, le=100)
    acceptance_criteria: list[str] = Field(min_length=1)
    checks: list[Check] = Field(min_length=1, max_length=10)

    @field_validator("allowed_paths")
    @classmethod
    def paths(cls, values: list[str]) -> list[str]:
        return [safe_path(value) for value in values]

    @field_validator("module")
    @classmethod
    def module_path(cls, value: str) -> str:
        return safe_path(value)

    @field_validator("dependencies", "resources")
    @classmethod
    def unique_labels(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("Values must be unique")
        return values


class Plan(StrictModel):
    version: Literal["1.0"] = "1.0"
    project: dict[str, str]
    architecture: dict[str, list[str]]
    contracts: list[dict[str, Any]] = Field(min_length=1)
    tasks: list[TaskSpec] = Field(min_length=1, max_length=20)
    final_checks: list[Check] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def dag(self) -> "Plan":
        ids = {task.id for task in self.tasks}
        if len(ids) != len(self.tasks):
            raise ValueError("Duplicate task ID")
        remaining = set(ids)
        for task in self.tasks:
            if task.id in task.dependencies or set(task.dependencies) - ids:
                raise ValueError(f"Invalid dependencies: {task.id}")
            if not {"build", "unit"}.issubset({check.layer for check in task.checks}):
                raise ValueError(f"Task {task.id} requires build and unit verification")
        if not any(check.layer == "integration" for check in self.final_checks):
            raise ValueError("Final integration verification is mandatory")
        while remaining:
            ready = {
                task.id
                for task in self.tasks
                if task.id in remaining and not set(task.dependencies) & remaining
            }
            if not ready:
                raise ValueError("Dependency cycle")
            remaining -= ready
        return self


class Proposal(StrictModel):
    status: Literal["submitted"] = "submitted"
    summary: str = Field(max_length=4000)
    files: dict[str, str] = Field(min_length=1, max_length=50)

    @field_validator("files")
    @classmethod
    def validate_files(cls, files: dict[str, str]) -> dict[str, str]:
        if sum(len(value.encode()) for value in files.values()) > 2_000_000:
            raise ValueError("Proposal exceeds 2 MB")
        for path in files:
            safe_path(path)
        if len({path.casefold() for path in files}) != len(files):
            raise ValueError("Case-insensitive path collision")
        return files


class Finding(StrictModel):
    severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    category: str
    file: str = ""
    line: int | None = None
    message: str
    evidence: str
    suggested_fix: str
    blocking: bool


class Review(StrictModel):
    findings: list[Finding]


class AgentInput(StrictModel):
    run_id: str
    task_id: str
    project_id: str
    role: str
    repository: dict[str, str]
    contract_version: str
    task: dict[str, Any]
    constraints: dict[str, Any]
    context: dict[str, Any]


class CheckResult(StrictModel):
    name: str
    layer: str
    status: Literal["passed", "failed", "cancelled"]
    command: list[str]
    exit_code: int | None
    duration_ms: int
    stdout: str = ""
    stderr: str = ""
    error_type: str | None = None
