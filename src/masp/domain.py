"""Canonical v1 API and agent contract. All external inputs are validated here."""

import json
import re
from enum import StrEnum
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
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
    link_repository: bool = False
    language: str = Field(default="auto", min_length=1, max_length=40)
    provider: Literal["fixture", "openai-compatible"] = "fixture"


class RunCreate(StrictModel):
    requirement: str = Field(min_length=5, max_length=16000)
    max_agents: int = Field(default=2, ge=1, le=64)
    max_retries: int = Field(default=3, ge=0, le=5)
    max_runtime: int = Field(default=1200, ge=1, le=3600)
    max_tokens: int = Field(default=2000000, ge=1000, le=10000000)
    inject_failure: bool = False
    approve_contract_change: bool = False
    execution_mode: Literal["docker", "local"] = "docker"
    conversation_id: str | None = None


class ConversationCreate(StrictModel):
    project_id: str | None = None
    model_profile_id: str | None = None
    title: str = Field(default="新对话", min_length=1, max_length=120)


class ChatMessageCreate(StrictModel):
    content: str = Field(min_length=1, max_length=32000)
    previous_run_id: str | None = None
    agent_id: str | None = Field(default=None, max_length=41)
    model_profile_id: str | None = None
    project_id: str | None = None
    access_mode: Literal["read", "files", "commands"] = "commands"
    command_timeout_seconds: int = Field(default=120, ge=30, le=120)
    max_context_tokens: int = Field(default=64000, ge=4000, le=256000)
    autonomous_hours: float = Field(default=8, ge=0.01, le=8)
    auto_compact: bool = True
    execute_team_now: bool = False
    team_version: int | None = None
    execute_plan_now: bool = False
    plan_id: str | None = None
    main_only: bool = False
    attachments: list[dict[str, str]] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def bounded_attachments(self) -> "ChatMessageCreate":
        if any(
            len(item.get("content", "")) > 250_000 or len(item.get("data_url", "")) > 14_000_000
            for item in self.attachments
        ):
            raise ValueError("文本附件最大 250 KB，二进制附件最大 10 MB")
        if (
            sum(
                len(item.get("content", "")) + len(item.get("data_url", ""))
                for item in self.attachments
            )
            > 35_000_000
        ):
            raise ValueError("本轮附件编码总量最大 35 MB")
        return self


class PlanStep(StrictModel):
    step_number: int
    title: str
    description: str = ""
    assigned_agent: str = "main"
    target_files: list[str] = Field(default_factory=list)
    status: Literal["pending", "running", "done", "failed"] = "pending"


class ExecutionPlan(StrictModel):
    plan_id: str
    title: str
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)
    requires_subagents: bool = False
    status: Literal["waiting_approval", "approved", "executing", "completed"] = "waiting_approval"


class SkillInput(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    content: str = Field(min_length=1, max_length=64000)


class McpServerInput(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    transport: Literal["stdio", "http"] = "stdio"
    command: str = Field(default="", max_length=1000)
    args: list[str] = Field(default_factory=list, max_length=30)
    url: str | None = Field(default=None, max_length=1000)
    enabled: bool = False
    env: dict[str, str] = Field(default_factory=dict, max_length=40)
    headers: dict[str, str] = Field(default_factory=dict, max_length=40)
    cwd: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def valid_transport(self) -> "McpServerInput":
        if self.transport == "stdio" and not self.command.strip():
            raise ValueError("stdio MCP 服务需要填写启动命令")
        if self.transport == "http":
            if not self.url or not self.url.startswith(
                ("https://", "http://localhost:", "http://127.0.0.1:")
            ):
                raise ValueError("HTTP MCP 服务需要 HTTPS 或本机 HTTP 地址")
        return self


class PluginInput(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=1000)
    command: str = Field(min_length=1, max_length=1000)
    args: list[str] = Field(default_factory=list, max_length=30)
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    enabled: bool = False

    @field_validator("parameters")
    @classmethod
    def object_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            serialized = json.dumps(value, ensure_ascii=False)
            Draft202012Validator.check_schema(value)
        except (SchemaError, TypeError, ValueError) as error:
            raise ValueError("Plugin parameters must be a valid JSON Schema") from error
        if value.get("type") != "object" or len(serialized) > 16000:
            raise ValueError("Plugin parameters must be a bounded object schema")
        return value


class ModelProfileInput(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=160)
    api_key: str | None = Field(default=None, max_length=4000)
    temperature: float = Field(default=0.2, ge=0, le=2)
    top_p: float = Field(default=1.0, gt=0, le=1)
    max_output_tokens: int = Field(default=8192, ge=256, le=32768)
    timeout_seconds: int = Field(default=90, ge=10, le=300)

    @field_validator("base_url")
    @classmethod
    def compatible_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith(("https://", "http://localhost:", "http://127.0.0.1:")):
            raise ValueError("Use HTTPS or a local HTTP model endpoint")
        return value


class TeamAgentInput(StrictModel):
    system_prompt: str = Field(default="", max_length=32000)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,40}$")
    name: str = Field(min_length=1, max_length=80)
    responsibility: str = Field(min_length=1, max_length=32000)
    model_profile_id: str
    owned_paths: list[str] = Field(default_factory=list, max_length=30)
    locked: bool = False

    @field_validator("owned_paths")
    @classmethod
    def paths(cls, values: list[str]) -> list[str]:
        return [safe_path(value) for value in values]


class TeamInput(StrictModel):
    requirement: str = Field(min_length=5, max_length=16000)
    main_profile_id: str
    review_profile_id: str | None = None
    review_mode: Literal["adaptive", "internal", "open-code-review"] = "adaptive"
    agents: list[TeamAgentInput] = Field(min_length=1, max_length=64)
    max_concurrency: int = Field(default=2, ge=1, le=64)
    version: int | None = None
    conversation_id: str | None = None

    @model_validator(mode="after")
    def unique_agents(self) -> "TeamInput":
        if len({agent.id for agent in self.agents}) != len(self.agents):
            raise ValueError("Duplicate agent ID")
        return self


class TeamStart(StrictModel):
    requirement: str | None = Field(default=None, min_length=5, max_length=16000)
    execution_mode: Literal["docker", "local"] = "local"
    previous_run_id: str | None = None
    conversation_id: str | None = None


class TeamGenerate(StrictModel):
    requirement: str = Field(min_length=5, max_length=16000)
    main_profile_id: str
    max_concurrency: int = Field(default=2, ge=1, le=64)
    instruction: str | None = Field(default=None, max_length=4000)
    conversation_id: str | None = None


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
    agent_id: str | None = None
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
