"""MASP Supervisor Multi-Agent Engine.

Inspired by bytedance/deer-flow and langchain-ai/langgraph-supervisor-py:
- Dynamic Subagent Lifecycle: The Main Agent (Supervisor) creates, adjusts,
  and coordinates specialized subagents on the fly based on user intent.
- Autonomous ReAct Execution: Subagents run full ReAct loops with complete workspace
  tool access (no artificial file-path cages or rigid owned_paths lockdowns).
- Interactive Collaboration Mindmap: Synchronizes dynamic subagent graph and states
  with the live team mindmap (event: team and event: subagent_progress).
- Pause & Resume: Users can pause the conversation, manually adjust subagent
  prompts or routing models, and resume execution.
- Autonomous Verification: Self-correction and re-testing when commands fail.
- Clean Output: Filters raw DSML/tool call tokens from conversational text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from masp._vendor.deerflow.tool_receipt import ToolReceipt
from masp.agents import extract_dsml_tool_calls
from masp.chat_tools import run_chat_tool
from masp.compaction import RepeatToolReminder, ToolResultPruner, build_deterministic_summary
from masp.cordis_runtime import NativeToolOutput, native_context_messages
from masp.managed_commands import run_cancellable_tool
from masp.model_runtime import (
    ModelRecovery,
    compatible_model_stream,
    complete_stream_result,
    configure_provider,
    evaluate_report,
    evidence_context,
    merge_stream_identifier,
    model_stream_lines,
    preserve_partial_response,
    requests_execution,
    response_deadline,
    stamp_receipt,
)
from masp.storage import now
from masp.work_budget import compact_runtime_messages
from masp.workspace_coordination import WorkspaceCoordinator

logger = logging.getLogger(__name__)

# Supervisor Tools exposed to the Lead Agent when in Multi-Agent Mode
SUPERVISOR_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "remove_subagent",
            "description": "强制停止并清除失败或不再需要的子代理，再尝试其他解决方案。",
            "parameters": {
                "type": "object",
                "properties": {"subagent_name": {"type": "string"}},
                "required": ["subagent_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_subagents",
            "description": "一次创建并启动多个独立子代理，立即返回，主 Agent 可同时继续工作。无需先 create_subagent。用 wait_subagents 获取完成报告；有依赖的任务等前置报告后再启动。清理与重建必须用 depends_on 声明依赖。owned_paths 声明负责的文件或目录；不同路径可并行，同路径或未声明路径的写任务会排队，主 Agent 也遵守文件锁。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 64,
                        "items": {
                            "type": "object",
                            "properties": {
                                "subagent_name": {"type": "string"},
                                "prompt": {"type": "string"},
                                "role": {"type": "string"},
                                "model": {"type": "string"},
                                "acceptance_criteria": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "owned_paths": {"type": "array", "items": {"type": "string"}},
                                "depends_on": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["subagent_name", "prompt"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["tasks"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_subagents",
            "description": "获取后台子代理完成报告，默认等待第一个完成，其他继续执行。已经返回的报告不重复提交；全部完成前不能宣称整个任务完成。",
            "parameters": {
                "type": "object",
                "properties": {"timeout_seconds": {"type": "number", "minimum": 0, "maximum": 60}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_subagent",
            "description": "创建或配置子代理而不启动执行。需要批量创建并立即并行执行时优先使用 start_subagents。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "子代理英文标识符，例如 test_engineer, ui_designer, logic_dev, refactor_specialist",
                    },
                    "role": {
                        "type": "string",
                        "description": "子代理角色名称（如 测试与质量工程师、前端动画工程师）",
                    },
                    "description": {
                        "type": "string",
                        "description": "子代理职责概述与分工范围",
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "可选：为该子代理量身定制的专属系统提示词与工作规范",
                    },
                    "model": {
                        "type": "string",
                        "description": "可选：该子代理指定的路由模型名称或模型配置 ID",
                    },
                },
                "required": ["name", "role", "description"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_subagent_task",
            "description": "分配一个任务并等待其完成，会阻塞主 Agent。主 Agent 也有独立工作或有多个独立任务时，优先使用 start_subagents 后继续执行，再用 wait_subagents 获取报告。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subagent_name": {
                        "type": "string",
                        "description": "目标子代理标识符",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "具体任务指令、上下文信息与交付标准",
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选的验收指标清单（如测试命令、文件产出要求等）",
                    },
                },
                "required": ["subagent_name", "prompt"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_subagents_parallel",
            "description": "并行执行多个任务并等待整批完成。需要主 Agent 同时执行或逐个接收报告时，使用 start_subagents 和 wait_subagents。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "subagent_name": {"type": "string"},
                                "prompt": {"type": "string"},
                                "acceptance_criteria": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["subagent_name", "prompt"],
                        },
                        "description": "要并发执行的子代理任务列表",
                    },
                },
                "required": ["tasks"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adjust_subagent",
            "description": "动态调整已存在子代理的角色、系统提示词、职责或路由模型。主 Agent 或用户可以在运行过程中对其进行动态优化。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subagent_name": {
                        "type": "string",
                        "description": "目标子代理标识符",
                    },
                    "role": {"type": "string", "description": "新角色名称"},
                    "description": {"type": "string", "description": "新职责描述"},
                    "system_prompt": {"type": "string", "description": "新系统提示词"},
                    "model": {"type": "string", "description": "新路由模型"},
                },
                "required": ["subagent_name"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass
class SubagentSpec:
    """Specification and runtime state of a dynamic subagent."""

    id: str
    name: str
    role: str
    responsibility: str
    system_prompt: str = ""
    model_profile_id: str | None = None
    status: str = "ready"  # ready, running, completed, failed
    owned_paths: list[str] = field(
        default_factory=list
    )  # Empty: full workspace access without path cage
    current_task: str = ""
    last_report: str = ""
    steps: list[dict[str, str]] = field(default_factory=list)
    thinking: str = ""
    progress_pct: int = 0
    effective_model: str = ""
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)

    def to_team_agent_dict(self) -> dict[str, Any]:
        """Convert to dict representation used by the frontend Collaboration Mindmap."""
        return {
            "id": self.id,
            "name": self.name or self.role,
            "role": self.role or self.name,
            "responsibility": self.responsibility,
            "system_prompt": self.system_prompt,
            "model_profile_id": self.model_profile_id or "",
            "effective_model": self.effective_model,
            "status": self.status,
            "owned_paths": self.owned_paths,
            "current_task": self.current_task,
            "progress_pct": self.progress_pct,
            "steps": self.steps,
            "thinking": self.thinking,
        }

    def to_progress_event_dict(self) -> dict[str, Any]:
        """Convert to payload for SSE event: subagent_progress."""
        return {
            "agent_id": self.id,
            "model_profile_id": self.model_profile_id or "",
            "effective_model": self.effective_model,
            "agent_name": self.name or self.role,
            "role": self.role or self.name,
            "status": self.status,
            "detail": self.current_task or self.responsibility,
            "thinking": self.thinking,
            "error": self.thinking if self.status == "failed" else None,
            "steps": self.steps,
            "progress_pct": self.progress_pct,
            "updated_at": self.updated_at,
        }


def clean_raw_model_tokens(text: str) -> str:
    """Remove raw DSML / tool call XML / internal tags from text before streaming to user.

    Prevents raw blocks like <｜｜DSML｜｜ ...> </｜｜DSML｜｜ calls> or
    <tool_call>...</tool_call> from leaking into the user chat area.
    """
    if not text:
        return ""
    text = re.sub(r"<tool-execution-memory>[\s\S]*?(?:</tool-execution-memory>|$)", "", text)
    # Strip DSML calls block
    cleaned = re.sub(
        r"<[|｜]{1,2}DSML[|｜]{1,2}\s+calls>[\s\S]*?(?:</[|｜]{1,2}DSML[|｜]{1,2}\s+calls>|$)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Strip single DSML invoke tags
    cleaned = re.sub(
        r"<[|｜]{1,2}DSML[|｜]{1,2}\s+invoke[^>]*>[\s\S]*?(?:</[|｜]{1,2}DSML[|｜]{1,2}\s+invoke>|$)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Strip <tool_call>...</tool_call>
    cleaned = re.sub(
        r"<tool_call>[\s\S]*?(?:</tool_call>|$)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Strip raw configure_team / start_team
    cleaned = re.sub(
        r"<configure_team>[\s\S]*?(?:</configure_team>|$)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"<start_team>[\s\S]*?(?:</start_team>|$)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Strip FIM / token artifacts
    cleaned = re.sub(
        r"<\|fim_[a-z]+\|>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


class SupervisorManager:
    """Manages the dynamic multi-agent supervisor loop and subagents."""

    def __init__(
        self,
        workspace_root: Path,
        conversation_id: str,
        initial_team: dict[str, Any] | None = None,
        skills_home: Path | None = None,
        access_mode: str = "commands",
        parent_context: list[dict[str, Any]] | None = None,
        max_concurrency: int = 4,
        tool_executor: Callable[[str, str], Any] | None = None,
        refresh_tools: Callable[[], list[dict[str, Any]]] | None = None,
    ):
        self.workspace_root = workspace_root
        self.conversation_id = conversation_id
        self.skills_home = skills_home
        self.access_mode = access_mode
        self.subagents: dict[str, SubagentSpec] = {}
        self.team_obj = dict(initial_team or {})
        self.team_obj.setdefault("id", f"team-{conversation_id}")
        self.parent_context = parent_context or []
        self.tool_executor = tool_executor
        self.refresh_tools = refresh_tools
        self.capacity = asyncio.Semaphore(max(1, max_concurrency))
        self.agent_locks: dict[str, asyncio.Lock] = {}
        self.background_tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self.task_executions: dict[tuple[Any, ...], asyncio.Task[dict[str, Any]]] = {}
        self.assigned_prompts: dict[str, str] = {}
        self.delegation_started = False
        self.require_team_approval = False
        self.coordinator = WorkspaceCoordinator(workspace_root)
        self.completed_reports: dict[str, dict[str, Any]] = {}
        self.histories: dict[str, list[dict[str, Any]]] = self.team_obj.get("histories", {})

        # Initialize existing subagents from team_obj if present
        if self.team_obj.get("agents"):
            for ag in self.team_obj["agents"]:
                ag_id = ag.get("id") or ag.get("name") or "agent"
                self.subagents[ag_id] = SubagentSpec(
                    id=ag_id,
                    name=ag.get("name") or ag_id,
                    role=ag.get("role") or ag.get("name") or ag_id,
                    responsibility=ag.get("responsibility") or "",
                    system_prompt=ag.get("system_prompt") or "",
                    model_profile_id=ag.get("model_profile_id") or None,
                    status=ag.get("status") or "ready",
                    owned_paths=list(ag.get("owned_paths") or []),
                )

    def create_subagent(
        self,
        name: str,
        role: str,
        description: str,
        system_prompt: str = "",
        model: str | None = None,
    ) -> SubagentSpec:
        """Create or register a dynamic subagent."""
        clean_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip().lower()) or "subagent"
        if clean_name in self.subagents:
            existing = self.subagents[clean_name]
            existing.role = role.strip() or existing.role
            existing.responsibility = description.strip()
            if system_prompt:
                existing.system_prompt = system_prompt.strip()
            if model is not None:
                existing.model_profile_id = model.strip() or None
            self._sync_team_obj()
            return existing
        spec = SubagentSpec(
            id=clean_name,
            name=clean_name,
            role=role.strip() or clean_name,
            responsibility=description.strip(),
            system_prompt=system_prompt.strip(),
            model_profile_id=model.strip() if model else None,
            status="ready",
            steps=[
                {"id": "init", "label": f"子代理 {role} 已就绪", "status": "done"},
            ],
            thinking=f"主 Agent 创建了子代理「{role}」，负责：{description.strip()}",
        )
        self.subagents[clean_name] = spec
        self._sync_team_obj()
        return spec

    def start_subagents(self, tasks: Any, **kwargs: Any) -> dict[str, Any]:
        """Validate the whole batch before scheduling; retain tasks until collected."""
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 64:
            raise ValueError("tasks must contain 1–64 independent tasks")
        names: list[str] = []
        for item in tasks:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("subagent_name"), str)
                or not isinstance(item.get("prompt"), str)
                or not item["prompt"].strip()
            ):
                raise ValueError("Each task needs a subagent_name and nonempty prompt")
            name = re.sub(r"[^a-zA-Z0-9_-]", "_", item["subagent_name"].strip().lower())
            if not name or name in names:
                raise ValueError("Duplicate subagent: " + name)
            if name in self.background_tasks and (
                self.assigned_prompts.get(name) != item["prompt"].strip()
                or (
                    "owned_paths" in item
                    and item["owned_paths"] != self.subagents[name].owned_paths
                )
            ):
                raise ValueError("Collect the existing task before replacing subagent: " + name)
            if item.get("acceptance_criteria") is not None and (
                not isinstance(item["acceptance_criteria"], list)
                or not all(isinstance(c, str) for c in item["acceptance_criteria"])
            ):
                raise ValueError("acceptance_criteria must be a list of strings")
            if any(key in item and not isinstance(item[key], str) for key in ("role", "model")):
                raise ValueError("role and model must be strings")
            names.append(name)
        if len(set(self.background_tasks) | set(names)) > 64:
            raise ValueError("Collect existing reports before starting more than 64 tasks")
        dependencies = {
            name: item.get("depends_on") or [] for name, item in zip(names, tasks, strict=True)
        }
        for name, item in zip(names, tasks, strict=True):
            for field_name in ("owned_paths", "depends_on"):
                if field_name in item and (
                    not isinstance(item[field_name], list)
                    or not all(isinstance(value, str) for value in item[field_name])
                ):
                    raise ValueError(field_name + " must be a list of strings")
            self.coordinator.paths(item.get("owned_paths") or [])
            if any(
                dep == name
                or dep not in set(names) | set(self.background_tasks) | set(self.completed_reports)
                for dep in dependencies[name]
            ):
                raise ValueError("Unknown/self task dependency")
        order: list[str] = []
        visited: set[str] = set()

        def visit(name: str, trail: set[str]) -> None:
            if name in trail:
                raise ValueError("Cyclic task dependency")
            if name in visited:
                return
            for dep in dependencies.get(name, []):
                visit(dep, trail | {name})
            visited.add(name)
            if name in dependencies:
                order.append(name)

        for name in names:
            visit(name, set())

        if self.require_team_approval:
            self.subagents.clear()
            for name, item in zip(names, tasks, strict=True):
                self.create_subagent(name, item.get("role") or name, item["prompt"], model=None)
                self.subagents[name].owned_paths = list(item.get("owned_paths") or [])
            self.team_obj.update(status="draft", workflow_state="planned", pending_tasks=tasks)
            self._sync_team_obj()
            directory = self.workspace_root / ".masp" / "team-plans"
            directory.mkdir(parents=True, exist_ok=True)
            document_root = directory / (
                self.conversation_id + "-v" + str(self.team_obj.get("version", 1))
            )
            document_root.mkdir(exist_ok=True)
            documents = {
                "requirements.md": "# 本轮需求\n\n"
                + str(self.team_obj.get("requirement") or "")
                + "\n",
                "design.md": "# 协作设计\n\n先审核本方案，确认后执行。按任务依赖和文件归属协调；失败任务可停止并清除，重新选择解决方案。\n\n"
                + "\n".join(
                    "- "
                    + item["subagent_name"]
                    + "："
                    + str(item.get("role") or item["subagent_name"])
                    + "；负责文件："
                    + ", ".join(item.get("owned_paths") or [])
                    + "；依赖："
                    + ", ".join(item.get("depends_on") or [])
                    for item in tasks
                )
                + "\n",
                "tasks.md": "# 完整任务分配\n\n"
                + "\n\n".join(
                    "## "
                    + item["subagent_name"]
                    + "\n\n模型："
                    + str(item.get("model") or "继承主模型")
                    + "\n\n任务与提示词：\n\n"
                    + item["prompt"]
                    + "\n\n验收标准：\n"
                    + "\n".join(
                        "- " + str(value) for value in item.get("acceptance_criteria") or []
                    )
                    for item in tasks
                )
                + "\n",
            }
            for filename, content in documents.items():
                (document_root / filename).write_text(content, encoding="utf-8")
            self.team_obj["plan_documents"] = [
                (document_root / filename).relative_to(self.workspace_root).as_posix()
                for filename in documents
            ]
            (
                directory
                / (self.conversation_id + "-v" + str(self.team_obj.get("version", 1)) + ".json")
            ).write_text(json.dumps(self.team_obj, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "status": "awaiting_approval",
                "subagents": [],
                "message": "方案已提交用户审核。等待用户确认，禁止启动或替代执行子任务。",
            }

        async def dispatch_unlocked(name: str, item: dict[str, Any]) -> dict[str, Any]:
            for dependency in dependencies[name]:
                predecessor = self.background_tasks.get(dependency)
                report = await predecessor if predecessor else self.completed_reports[dependency]
                if report.get("status") != "completed":
                    spec = self.subagents[name]
                    spec.status = "failed"
                    spec.thinking = "前置任务未完成，禁止继续修改工作区"
                    await kwargs["emit_event"]("subagent_progress", spec.to_progress_event_dict())
                    return {"status": "failed", "subagent_name": name, "error": spec.thinking}
            return await self.execute_subagent_task(
                name, item["prompt"], item.get("acceptance_criteria"), **kwargs
            )

        async def dispatch(name: str, item: dict[str, Any]) -> dict[str, Any]:
            try:
                return await dispatch_unlocked(name, item)
            finally:
                await self.coordinator.release_reservation(name)

        for name in order:
            item = tasks[names.index(name)]
            if name in self.background_tasks:
                continue
            self.assigned_prompts[name] = item["prompt"].strip()
            self.delegation_started = True
            if name not in self.subagents:
                self.create_subagent(
                    name, item.get("role") or name, item["prompt"][:200], model=None
                )
            elif "model" in item or item.get("role"):
                self.adjust_subagent(name, role=item.get("role"), model=None)
            if "owned_paths" in item:
                self.subagents[name].owned_paths = list(item["owned_paths"])
            if any(
                tool["function"]["name"]
                not in {
                    "read_file",
                    "list_files",
                    "search_files",
                    "web_search",
                    "web_fetch",
                    "memory_search",
                }
                for tool in kwargs.get("sub_tools", [])
            ):
                self.coordinator.reserve(name, self.subagents[name].owned_paths)
            self.background_tasks[name] = asyncio.create_task(
                dispatch(name, item), name=f"subagent:{name}"
            )
        return {"status": "started", "subagents": names, "background": True}

    async def wait_subagents(self, timeout_seconds: float = 10) -> dict[str, Any]:
        """Return completed work immediately, otherwise wake on the first completion."""
        timeout = max(0.0, min(60.0, float(timeout_seconds)))
        if self.background_tasks and not any(
            task.done() for task in self.background_tasks.values()
        ):
            await asyncio.wait(
                set(self.background_tasks.values()),
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        reports = []
        for name, task in list(self.background_tasks.items()):
            if not task.done():
                continue
            try:
                report = task.result()
            except asyncio.CancelledError:
                report = {"status": "cancelled", "subagent_name": name}
            except Exception as exc:
                report = {"status": "failed", "subagent_name": name, "error": str(exc)}
            reports.append(report)
            self.completed_reports[name] = report
            del self.background_tasks[name]
        return {"reports": reports, "pending": list(self.background_tasks)}

    def adjust_subagent(
        self,
        name: str,
        role: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> SubagentSpec | None:
        """Adjust an existing subagent's specification."""
        clean_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip().lower())
        spec = self.subagents.get(clean_name)
        if not spec:
            return None
        if model is not None and (model.strip() or None) != spec.model_profile_id:
            # A human model change starts a new execution generation, even when
            # switching back to a model used earlier in this turn.
            for key, operation in list(self.task_executions.items()):
                if key[0] == clean_name and operation.done():
                    self.task_executions.pop(key, None)
        if role:
            spec.role = role.strip()
        if description:
            spec.responsibility = description.strip()
        if system_prompt is not None:
            spec.system_prompt = system_prompt.strip()
        if model is not None:
            spec.model_profile_id = model.strip() or None
        spec.updated_at = now()
        self._sync_team_obj()
        return spec

    def apply_team_update(self, team: dict[str, Any]) -> None:
        """Apply user edits before resuming without discarding execution state."""
        members = {ag["id"]: ag for ag in team.get("agents", [])}
        for name, ag in members.items():
            if name not in self.subagents:
                self.create_subagent(
                    name, ag.get("role") or ag.get("name") or name, ag.get("responsibility", "")
                )
            spec = self.subagents[name]
            spec.role = ag.get("role") or ag.get("name") or spec.role
            spec.responsibility = ag.get("responsibility", spec.responsibility)
            spec.system_prompt = ag.get("system_prompt", spec.system_prompt)
            self.adjust_subagent(name, model=ag.get("model_profile_id") or "")
            spec.owned_paths = list(ag.get("owned_paths") or [])
        for name in list(self.subagents):
            if name not in members:
                task = self.background_tasks.get(name)
                if task and not task.done():
                    task.cancel()
                self._cancel_assignments(name)
                self.subagents[name].status = "cancelled"
                del self.subagents[name]
        self._sync_team_obj()

    def _cancel_assignments(self, name: str) -> list[asyncio.Task[dict[str, Any]]]:
        operations = []
        for key, operation in list(self.task_executions.items()):
            if key[0] == name:
                self.task_executions.pop(key, None)
                if not operation.done():
                    operation.cancel()
                    operations.append(operation)
        self.assigned_prompts.pop(name, None)
        return operations

    async def remove_subagent(self, name: str) -> dict[str, Any]:
        operations = self._cancel_assignments(name)
        task = self.background_tasks.pop(name, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await asyncio.gather(*operations, return_exceptions=True)
        await self.coordinator.release_reservation(name)
        self.subagents.pop(name, None)
        self.histories.pop(name, None)
        self.completed_reports.pop(name, None)
        self._sync_team_obj()
        return {"status": "removed", "subagent_name": name}

    def _sync_team_obj(self) -> dict[str, Any]:
        """Keep team_obj in sync with active subagents."""
        agents_list = [spec.to_team_agent_dict() for spec in self.subagents.values()]
        self.team_obj["agents"] = agents_list
        self.team_obj["histories"] = self.histories
        self.team_obj["updated_at"] = now()
        return self.team_obj

    def get_team_event_data(self) -> dict[str, Any]:
        """Get the payload to emit as SSE event: team."""
        self._sync_team_obj()
        return {
            **self.team_obj,
            "conversation_id": self.conversation_id,
            "status": "draft" if self.require_team_approval else "approved",
            "workflow_state": "planned" if self.require_team_approval else "running",
            "first_turn_confirm": False,
            "agents": [s.to_team_agent_dict() for s in self.subagents.values()],
            "version": int(self.team_obj.get("version") or 1),
            "plan_version": int(self.team_obj.get("plan_version") or 1),
            "updated_at": now(),
        }

    async def execute_subagent_task(
        self,
        subagent_name: str,
        task_prompt: str,
        acceptance_criteria: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """One execution per assignment per turn, shared by every dispatch tool."""
        if self.require_team_approval:
            return await self._dispatch_subagent_task(
                subagent_name, task_prompt, acceptance_criteria, **kwargs
            )
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", subagent_name.strip().lower()) or "subagent"
        spec = self.subagents.get(name)
        key = (
            name,
            task_prompt.strip(),
            spec.model_profile_id if spec else None,
            spec.system_prompt if spec else "",
            tuple(spec.owned_paths) if spec else (),
        )
        existing = self.task_executions.get(key)
        if (
            existing is not None
            and existing.done()
            and (
                existing.cancelled()
                or existing.exception() is not None
                or existing.result().get("status") != "completed"
            )
        ):
            self.task_executions.pop(key, None)
            existing = None
        if existing is not None:
            result = dict(await asyncio.shield(existing))
            result["reused_execution"] = True
            if acceptance_criteria:
                result["requested_acceptance_criteria"] = acceptance_criteria
                result["reuse_note"] = (
                    "同一轮的同一任务已执行；复用真实报告，新增验收条件由主代理核查。"
                )
            return result
        operation = asyncio.create_task(
            self._dispatch_subagent_task(name, task_prompt, acceptance_criteria, **kwargs)
        )
        self.task_executions[key] = operation
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise

    async def _dispatch_subagent_task(
        self,
        subagent_name: str,
        task_prompt: str,
        acceptance_criteria: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self.require_team_approval:
            result = self.start_subagents(
                [
                    {
                        "subagent_name": subagent_name,
                        "prompt": task_prompt,
                        "acceptance_criteria": acceptance_criteria or [],
                    }
                ]
            )
            await kwargs["emit_event"]("team", self.get_team_event_data())
            return result
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", subagent_name.strip().lower()) or "subagent"
        self.delegation_started = True
        lock = self.agent_locks.setdefault(name, asyncio.Lock())
        queued_at = time.monotonic()
        started_at = queued_at

        async def run() -> dict[str, Any]:
            nonlocal started_at
            spec = self.subagents.get(name)
            if spec and not lock.locked():
                spec.status = "running"
                spec.thinking = "等待可用执行槽位…"
                spec.updated_at = now()
                await kwargs["emit_event"]("subagent_progress", spec.to_progress_event_dict())
            from contextlib import AsyncExitStack

            async with AsyncExitStack() as stack:
                await stack.enter_async_context(lock)
                tools = kwargs.get("sub_tools") or []
                writable = any(
                    t["function"]["name"]
                    not in {
                        "read_file",
                        "list_files",
                        "search_files",
                        "web_search",
                        "web_fetch",
                        "memory_search",
                    }
                    for t in tools
                )
                if writable:
                    await stack.enter_async_context(
                        self.coordinator.lease(name, spec.owned_paths if spec else [])
                    )
                await stack.enter_async_context(self.capacity)
                started_at = time.monotonic()
                report = await self._execute_subagent_task(
                    name, task_prompt, acceptance_criteria, **kwargs
                )
                report.setdefault("subagent_name", name)
                report["timing"] = {
                    "queue_seconds": round(started_at - queued_at, 4),
                    "execution_seconds": round(time.monotonic() - started_at, 4),
                    "total_seconds": round(time.monotonic() - queued_at, 4),
                }
                return report

        # Bound the entire dispatch, including capacity waits and never-ending streams.
        timeout = float(kwargs.pop("task_timeout_seconds", 1800))
        task = asyncio.create_task(run())
        cancel_wait = asyncio.create_task(kwargs["cancel_event"].wait())
        try:
            done, _ = await asyncio.wait(
                {task, cancel_wait}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if cancel_wait in done:
                raise asyncio.CancelledError
            if task not in done:
                raise TimeoutError("子代理执行超时，请缩小任务后重试")
            return await task
        except asyncio.CancelledError:
            spec = self.subagents.get(name)
            if spec:
                spec.status = "cancelled"
                spec.last_report = "执行已取消"
                await kwargs["emit_event"]("subagent_progress", spec.to_progress_event_dict())
            return {"status": "cancelled", "subagent_name": name}
        except Exception as exc:
            spec = self.subagents.get(name)
            if spec:
                spec.status = "failed"
                spec.last_report = f"执行失败：{type(exc).__name__}: {exc}"
                spec.thinking = spec.last_report
                await kwargs["emit_event"]("subagent_progress", spec.to_progress_event_dict())
            return {"status": "failed", "subagent_name": name, "error": str(exc)}
        finally:
            task.cancel()
            cancel_wait.cancel()
            await asyncio.gather(task, cancel_wait, return_exceptions=True)

    async def _execute_subagent_task(
        self,
        subagent_name: str,
        task_prompt: str,
        acceptance_criteria: list[str] | None = None,
        *,
        client: Any,
        default_config: Any,
        load_model_config: Callable[[str | None], Any],
        sub_tools: list[dict[str, Any]],
        cancel_event: asyncio.Event,
        pause_event: asyncio.Event,
        emit_event: Callable[[str, dict[str, Any]], Any],
        max_turns: int = 10,
        recovery_max_attempts: int = 2,
        context_max_chars: int = 100000,
        batch_steps: int = 30,
        auto_compact: bool = True,
    ) -> dict[str, Any]:
        """Execute a subagent with full workspace tools in an autonomous ReAct loop."""
        worker_started = time.monotonic()
        spec = self.subagents.get(subagent_name)
        if not spec:
            # Auto-create if not yet explicitly registered
            spec = self.create_subagent(
                name=subagent_name,
                role=subagent_name,
                description=f"执行任务：{task_prompt[:60]}",
            )

        spec.status = "running"
        spec.current_task = task_prompt
        spec.progress_pct = 15
        spec.thinking = f"开始分析与执行任务：{task_prompt[:120]}..."
        spec.steps = [
            {"id": "plan", "label": "分析任务与工作区代码", "status": "running"},
            {"id": "act", "label": "调用工具进行修改与产出", "status": "pending"},
            {"id": "verify", "label": "运行测试与结果检验", "status": "pending"},
            {"id": "report", "label": "完成交付并汇总报告", "status": "pending"},
        ]
        spec.updated_at = now()

        # Emit initial progress
        await emit_event("subagent_progress", spec.to_progress_event_dict())
        await emit_event("team", self.get_team_event_data())

        # Resolve model configuration
        config_profile_id = spec.model_profile_id
        sub_cfg = (
            await asyncio.to_thread(load_model_config, spec.model_profile_id)
            if spec.model_profile_id
            else default_config
        )
        sub_headers = {"Authorization": f"Bearer {sub_cfg.api_key}"} if sub_cfg.api_key else {}

        # Build Acceptance criteria string if provided (modeled on Deer-Flow)
        criteria_str = ""
        if acceptance_criteria:
            criteria_str = "\n【任务验收指标 Checklist】\n" + "\n".join(
                f"- [ ] {c}" for c in acceptance_criteria
            )

        system_instructions = (
            f"你是 Micro-Multi 多 Agent 协作网络中的自主子代理：{spec.role} ({spec.name})。\n"
            f"职责说明：{spec.responsibility}\n"
            + (f"专属工作规约：{spec.system_prompt}\n" if spec.system_prompt else "")
            + "【工作空间与自主权】：\n"
            "1. 你只能使用本次提供的工具，并严格遵守任务分配的文件归属和只读要求。\n"
            "2. 只能调用本次工具清单实际提供的能力；未提供的工具不可调用。\n"
            "【ReAct 思考与实证执行要求】：\n"
            "1. 根据任务需要使用工具。问答或分析直接给出结论；开发任务实际修改并验证。不要重复主代理工作，也不要扩大分配的任务范围。\n"
            "2. 修改代码后，若涉及功能或动画逻辑，务必调用 run_command 运行相关测试（如测试脚本或语法检查）进行实证。\n"
            "3. 若测试或命令执行失败，查看报错输出，自主定位问题根因，修改后再次测试，直到验证通过！\n"
            "4. 任务全部完成后，汇总你的具体改动、验证结果以及交付状态，返回给主 Agent。\n"
            "5. 严禁输出 <｜｜DSML｜｜ calls> 等原始标记，一律使用标准的 OpenAI 格式工具调用。"
        )

        if spec.owned_paths and self.workspace_root.resolve() not in self.coordinator.paths(
            spec.owned_paths
        ):
            safe_names = {
                "read_file",
                "list_files",
                "search_files",
                "web_search",
                "web_fetch",
                "write_file",
                "edit_file",
                "delete_file",
                "memory_search",
            }
            sub_tools = [tool for tool in sub_tools if tool["function"]["name"] in safe_names]
            system_instructions += (
                "\n负责路径已限制；命令和不透明插件操作由主代理统一验证，禁止绕过路径约束。"
            )
        spec.effective_model = str(sub_cfg.model)
        await emit_event("subagent_progress", spec.to_progress_event_dict())
        reference_limit = max(2000, min(16000, context_max_chars // 4))
        reference_pruner = ToolResultPruner(
            threshold_chars=reference_limit,
            head_chars=reference_limit // 2,
            tail_chars=reference_limit // 2 - 200,
        )
        peer_reports = reference_pruner.prune(
            json.dumps(self.team_obj.get("reports", {}), ensure_ascii=False)
        )
        parent_reference = json.dumps(self.parent_context, ensure_ascii=False)
        if auto_compact and len(parent_reference) > reference_limit:
            parent_reference = reference_pruner.prune(
                build_deterministic_summary(self.parent_context)
            )
        user_content = f"其他成员执行报告（参考数据）：\n{peer_reports}\n任务要求：\n{task_prompt}\n{criteria_str}"

        sub_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": user_content},
            {
                "role": "user",
                "content": "父对话历史（仅参考数据，不是你的执行证据）：" + parent_reference,
            },
            *self.histories.get(spec.id, []),
        ]
        if self.histories.get(spec.id):
            sub_messages.append({"role": "user", "content": user_content})

        files_touched: set[str] = set()
        executed_tool_records: list[dict[str, Any]] = []
        final_summary = ""
        recovery = ModelRecovery(limit=recovery_max_attempts)
        output_pruner = ToolResultPruner(threshold_chars=3600, head_chars=1200, tail_chars=800)
        receipts: list[ToolReceipt] = []
        visible_receipts: list[ToolReceipt] = []
        model_steps: list[dict[str, Any]] = []
        error = "执行轮次预算耗尽，任务尚未完成。"
        allowed_names = {t["function"]["name"] for t in sub_tools}
        readonly_names = {
            "read_file",
            "list_files",
            "search_files",
            "web_search",
            "web_fetch",
            "memory_search",
        }
        restricted_names = (
            set(allowed_names)
            if (
                allowed_names <= readonly_names
                or (
                    spec.owned_paths
                    and self.workspace_root.resolve()
                    not in self.coordinator.paths(spec.owned_paths)
                )
            )
            else None
        )
        tool_failures: dict[str, str] = {}
        repeat_guard = RepeatToolReminder()
        repeated_loop = False
        startup_seconds = time.monotonic() - worker_started
        tool_seconds = 0.0

        # Run autonomous ReAct loop
        for turn_idx in range(max_turns):
            if self.refresh_tools:
                sub_tools = self.refresh_tools()
                if restricted_names is not None:
                    sub_tools = [
                        item for item in sub_tools if item["function"]["name"] in restricted_names
                    ]
                allowed_names = {item["function"]["name"] for item in sub_tools}
            if auto_compact:
                compact_runtime_messages(
                    sub_messages,
                    context_max_chars,
                    force=turn_idx > 0 and turn_idx % batch_steps == 0,
                )
            if cancel_event.is_set() or spec.id not in self.subagents:
                spec.status = "cancelled"
                spec.thinking = "用户取消了本次执行。"
                await emit_event("subagent_progress", spec.to_progress_event_dict())
                return {"status": "cancelled", "summary": "任务已被用户取消"}

            # Handle pause
            refresh_model_on_resume = False
            while pause_event.is_set():
                refresh_model_on_resume = True
                spec.status = "paused"
                spec.thinking = "对话已被用户暂停。可以在协作导图中手动调整模型或配置。"
                await emit_event("subagent_progress", spec.to_progress_event_dict())
                await asyncio.sleep(0.5)
                if cancel_event.is_set():
                    break

            if cancel_event.is_set() or spec.id not in self.subagents:
                spec.status = "cancelled"
                await emit_event("subagent_progress", spec.to_progress_event_dict())
                return {"status": "cancelled", "summary": "任务已被用户取消"}
            spec.status = "running"
            if refresh_model_on_resume or spec.model_profile_id != config_profile_id:
                config_profile_id = spec.model_profile_id
                sub_cfg = (
                    await asyncio.to_thread(load_model_config, config_profile_id)
                    if config_profile_id
                    else default_config
                )
            spec.effective_model = str(sub_cfg.model)
            sub_headers = {"Authorization": f"Bearer {sub_cfg.api_key}"} if sub_cfg.api_key else {}
            sub_messages[0]["content"] = system_instructions + (
                f"\n当前主责方向：{spec.responsibility}\n最新工作规约：{spec.system_prompt}\n本轮原始任务：{user_content}"
            )

            # Update step progress
            if turn_idx == 0:
                spec.steps[0]["status"] = "done"
                spec.steps[1]["status"] = "running"
                spec.progress_pct = 30
            spec.updated_at = now()
            await emit_event("subagent_progress", spec.to_progress_event_dict())

            ledger, visible_receipts = evidence_context(receipts)
            sub_messages[0]["content"] += (
                "\n你的报告必须为已执行动作引用工具收据，例如 [r1 write_file]。收据是执行证据，不代表功能验收通过。\n"
                + ledger
            )
            sub_payload = {
                "model": sub_cfg.model,
                "stream": True,
                "temperature": sub_cfg.temperature,
                "max_tokens": int(sub_cfg.max_output_tokens or 8192),
                "messages": sub_messages,
                "tools": sub_tools,
                "tool_choice": "auto",
            }

            configure_provider(sub_payload, sub_cfg.base_url, recovering=bool(recovery.records))
            accumulated_content = ""
            reasoning_content = ""
            finish_reason = None
            interrupted = False
            saw_done = False
            accumulated_tool_calls: dict[int, dict[str, Any]] = {}
            last_progress_emit = time.monotonic()

            request_started = time.monotonic()

            async def model_heartbeat(request_started: float = request_started) -> None:
                elapsed = int(time.monotonic() - request_started)
                spec.thinking = (
                    # This callback is awaited within the current stream and needs live buffers.
                    clean_raw_model_tokens(reasoning_content[-4000:] or accumulated_content[-4000:])  # noqa: B023
                    or f"等待模型响应（{elapsed} 秒）…"
                )
                spec.updated_at = now()
                await emit_event("subagent_progress", spec.to_progress_event_dict())

            spec.thinking = "等待模型响应…"
            await emit_event("subagent_progress", spec.to_progress_event_dict())
            try:
                async with (
                    asyncio.timeout(response_deadline(sub_cfg)),
                    compatible_model_stream(
                        client,
                        "POST",
                        sub_cfg.base_url + "/chat/completions",
                        headers=sub_headers,
                        json=sub_payload,
                        timeout=max(15.0, float(getattr(sub_cfg, "timeout_seconds", 120))),
                    ) as response,
                ):
                    if response.status_code >= 400:
                        err_body = await response.aread()
                        error = f"模型请求失败 HTTP {response.status_code}: {err_body.decode(errors='replace')[:200]}"
                        logger.warning(
                            "Subagent %s model call failed: %s %s",
                            spec.name,
                            response.status_code,
                            err_body.decode(errors="replace")[:200],
                        )
                        if response.status_code == 429 or response.status_code >= 500:
                            hint = recovery.continuation(f"http_{response.status_code}")
                            if hint is not None and turn_idx < max_turns - 1:
                                sub_messages.append(hint)
                                error = ""
                                await asyncio.sleep(min(2 ** min(turn_idx, 3), 8))
                                continue
                        break

                    async for line in model_stream_lines(
                        response,
                        max(15.0, float(getattr(sub_cfg, "timeout_seconds", 120))),
                        model_heartbeat,
                    ):
                        if cancel_event.is_set():
                            break
                        if not line or not line.startswith("data:"):
                            continue
                        chunk_str = line[5:].strip()
                        if chunk_str == "[DONE]":
                            saw_done = True
                            break
                        try:
                            chunk_json = json.loads(chunk_str)
                        except Exception:
                            continue
                        choices = chunk_json.get("choices") or []
                        if not choices:
                            continue
                        finish_reason = (
                            choices[0].get("finish_reason")
                            or choices[0].get("stop_reason")
                            or finish_reason
                        )
                        delta = choices[0].get("delta") or {}
                        reasoning_content += delta.get("reasoning_content") or ""
                        if delta.get("content"):
                            accumulated_content += delta["content"]
                        if time.monotonic() - last_progress_emit >= 1:
                            spec.thinking = (
                                clean_raw_model_tokens(
                                    reasoning_content[-4000:] or accumulated_content[-4000:]
                                )
                                or "正在生成工具调用…"
                            )
                            spec.updated_at = now()
                            await emit_event("subagent_progress", spec.to_progress_event_dict())
                            last_progress_emit = time.monotonic()
                        if delta.get("tool_calls"):
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", 0)
                                if idx not in accumulated_tool_calls:
                                    accumulated_tool_calls[idx] = {
                                        "id": tc.get("id") or f"call_{idx}_{time.time_ns()}",
                                        "type": "function",
                                        "function": {
                                            "name": tc.get("function", {}).get("name") or "",
                                            "arguments": tc.get("function", {}).get("arguments")
                                            or "",
                                        },
                                    }
                                else:
                                    if tc.get("id"):
                                        accumulated_tool_calls[idx]["id"] = tc["id"]
                                    fn = tc.get("function") or {}
                                    if fn.get("name"):
                                        accumulated_tool_calls[idx]["function"]["name"] = (
                                            merge_stream_identifier(
                                                accumulated_tool_calls[idx]["function"]["name"],
                                                fn["name"],
                                            )
                                        )
                                    if fn.get("arguments"):
                                        accumulated_tool_calls[idx]["function"]["arguments"] += fn[
                                            "arguments"
                                        ]
            except Exception as ex:
                error = f"模型请求异常：{type(ex).__name__}: {ex}"
                logger.error("Error during subagent %s execution: %s", spec.name, ex)
                interrupted = True

            if (
                not saw_done
                and finish_reason is None
                and not cancel_event.is_set()
                and not complete_stream_result(accumulated_content, accumulated_tool_calls)
            ):
                interrupted = True
            model_steps.append(
                {
                    "turn": turn_idx + 1,
                    "model": str(sub_cfg.model),
                    "model_profile_id": spec.model_profile_id or "",
                    "finish_reason": finish_reason,
                    "reasoning_chars": len(reasoning_content),
                    "content_chars": len(accumulated_content),
                    "duration_seconds": round(time.monotonic() - request_started, 4),
                }
            )
            recovery_reason = recovery.reason(
                content=accumulated_content,
                calls=accumulated_tool_calls,
                finish_reason=finish_reason,
                reasoning=reasoning_content,
                interrupted=interrupted,
            )
            if recovery_reason:
                hint = recovery.continuation(recovery_reason)
                if hint is not None and turn_idx < max_turns - 1:
                    preserve_partial_response(
                        sub_messages, accumulated_content, reasoning_content, accumulated_tool_calls
                    )
                    sub_messages.append(hint)
                    await emit_event(
                        "model_recovery", {**recovery.records[-1], "agent_id": spec.id}
                    )
                    continue
                error = f"自动恢复未完成：{recovery_reason}"
                break
            if accumulated_tool_calls or (
                accumulated_content.strip() and not requests_execution(task_prompt)
            ):
                recovery.success()
            accumulated_content, embedded_calls = extract_dsml_tool_calls(accumulated_content)
            if not accumulated_tool_calls and embedded_calls:
                accumulated_tool_calls = dict(enumerate(embedded_calls))
            if cancel_event.is_set():
                error = "任务已被用户取消"
                break
            # If tool calls were made, execute them
            if accumulated_tool_calls:
                call_list = [
                    accumulated_tool_calls[k] for k in sorted(accumulated_tool_calls.keys())
                ]
                native_contexts: list[dict[str, Any]] = []
                native_concluded = False
                sub_messages.append(
                    {
                        "role": "assistant",
                        "content": accumulated_content or None,
                        "reasoning_content": reasoning_content,
                        "tool_calls": call_list,
                    }
                )

                for call_item in call_list:
                    fn_name = call_item["function"]["name"]
                    fn_args = call_item["function"]["arguments"]
                    call_id = call_item["id"]

                    if fn_name in {"write_file", "edit_file", "delete_file"}:
                        spec.steps[1]["status"] = "running"
                        spec.steps[2]["status"] = "pending"
                        spec.progress_pct = 50
                    elif fn_name == "run_command" and re.search(
                        r"pytest|npm (?:run )?test|\btsc\b|compileall|--check|\bruff\b|\bmypy\b",
                        fn_args,
                        re.IGNORECASE,
                    ):
                        spec.steps[1]["status"] = "done"
                        spec.steps[2]["status"] = "running"
                        spec.progress_pct = 75
                    spec.thinking = f"正在执行工具：{fn_name}"
                    spec.updated_at = now()
                    await emit_event("subagent_progress", spec.to_progress_event_dict())
                    # Invoke the same capability router as the lead; blocking commands
                    # run in a worker thread so other agents continue concurrently.
                    parsed_args: Any = {}
                    tool_started = time.monotonic()
                    try:
                        parsed_args = json.loads(fn_args)
                        if fn_name not in allowed_names:
                            raise ValueError(f"工具未授权：{fn_name}")

                        async def invoke_tool(
                            fn_name: str = fn_name, fn_args: str = fn_args
                        ) -> str:
                            async with self.coordinator.operation(fn_name, fn_args):
                                if self.tool_executor:
                                    return await self.tool_executor(fn_name, fn_args)
                                return await run_cancellable_tool(
                                    run_chat_tool,
                                    root=self.workspace_root,
                                    name=fn_name,
                                    arguments=fn_args,
                                    skills_home=self.skills_home,
                                    access_mode=self.access_mode,
                                    cancel_event=cancel_event,
                                )

                        tool_task = asyncio.create_task(invoke_tool())
                        tool_started = time.monotonic()
                        try:
                            while not tool_task.done():
                                await asyncio.wait({tool_task}, timeout=5.0)
                                if not tool_task.done():
                                    spec.thinking = f"正在执行工具：{fn_name}（{int(time.monotonic() - tool_started)} 秒）"
                                    spec.updated_at = now()
                                    await emit_event(
                                        "subagent_progress", spec.to_progress_event_dict()
                                    )
                            tool_output = await tool_task
                        finally:
                            tool_task.cancel()
                            await asyncio.gather(tool_task, return_exceptions=True)
                        if (
                            fn_name in {"write_file", "edit_file", "delete_file"}
                            and "path" in parsed_args
                        ):
                            files_touched.add(parsed_args["path"])
                    except Exception as exc:
                        failure_text = f"工具执行失败：{type(exc).__name__}: {exc}"
                        tool_output = (
                            NativeToolOutput(failure_text, exc.contract)
                            if hasattr(exc, "contract")
                            else failure_text
                        )
                    tool_seconds += time.monotonic() - tool_started
                    failure_key = (
                        fn_name + ":" + str(parsed_args.get("path", parsed_args.get("command", "")))
                        if isinstance(parsed_args, dict)
                        else fn_name
                    )
                    try:
                        receipt = json.loads(tool_output)
                    except (ValueError, TypeError):
                        receipt = None
                    if isinstance(receipt, dict):
                        failed = bool(
                            receipt.get("error")
                            or receipt.get("blocked")
                            or receipt.get("exit_code", 0)
                        )
                    else:
                        failed = tool_output.startswith(
                            ("工具执行失败", "工具错误", "读取失败", "读取工具未能完成")
                        )
                    if failed:
                        tool_failures[failure_key] = tool_output[:1000]
                    else:
                        tool_failures.pop(failure_key, None)

                    # Build tool event for UI visibility
                    tool_evt = {
                        "name": fn_name,
                        "arguments": fn_args,
                        "short_name": fn_name,
                        "category": "edit"
                        if fn_name in {"edit_file", "write_file", "delete_file"}
                        else "run",
                        "status": "failed" if failed else "complete",
                        "label": f"[{spec.role}] 执行 {fn_name}",
                        "output": tool_output[:3000],
                        "agent_id": spec.id,
                        "agent_name": spec.role,
                    }
                    native_result = getattr(tool_output, "contract", None)
                    if native_result:
                        tool_evt["native_result"] = native_result
                        native_contexts.extend(native_result.get("additionalContexts") or [])
                        native_concluded |= bool(
                            native_result.get("concludesTurn") and not native_result.get("isError")
                        )
                    receipts.append(
                        stamp_receipt(
                            len(receipts) + 1, fn_name, fn_args, tool_output, call_id, failed
                        )
                    )
                    executed_tool_records.append(tool_evt)
                    await emit_event("tool", tool_evt)

                    notice = repeat_guard.record(fn_name, fn_args)
                    if notice:
                        tool_output += "\n\n" + notice
                    if repeat_guard.repeat_count >= 8:
                        repeated_loop = True
                        error = "工具连续重复调用 8 次，未推进任务；已停止循环并保存进度。"

                    # Append tool message for ReAct loop
                    sub_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": output_pruner.prune(fn_name, tool_output),
                        }
                    )

                sub_messages.extend(native_context_messages(native_contexts, self.skills_home))
                if native_concluded:
                    final_summary = tool_output
                    error = ""
                    break
                if repeated_loop:
                    break
                # Continue next turn to let the subagent inspect outputs or complete
                continue
            else:
                # No tool calls; final answer from subagent
                final_summary = clean_raw_model_tokens(accumulated_content).strip()
                error = "" if final_summary else "模型返回空响应，任务尚未完成。"
                if (
                    final_summary
                    and requests_execution(task_prompt)
                    and not receipts
                    and any(
                        tool["function"]["name"]
                        in {"write_file", "edit_file", "delete_file", "run_command"}
                        for tool in sub_tools
                    )
                ):
                    hint = recovery.continuation("no_execution_evidence")
                    if hint is not None and turn_idx < max_turns - 1:
                        sub_messages.append(
                            {
                                "role": "assistant",
                                "content": final_summary,
                                "reasoning_content": reasoning_content,
                            }
                        )
                        sub_messages.append(hint)
                        continue
                    error = "没有实际执行证据，任务尚未交付。"
                if final_summary:
                    sub_messages.append(
                        {
                            "role": "assistant",
                            "content": final_summary,
                            "reasoning_content": reasoning_content,
                        }
                    )
                break

        # Mark subagent completed
        if cancel_event.is_set() or spec.id not in self.subagents:
            error = "任务已被用户取消"
        if tool_failures and not error:
            error = "存在未解决的工具错误：" + "\n".join(tool_failures.values())
        spec.status = (
            "cancelled"
            if cancel_event.is_set() or spec.id not in self.subagents
            else ("failed" if error else "completed")
        )
        self.histories[spec.id] = (
            sub_messages[3:]
            if self.histories.get(spec.id)
            else [sub_messages[1], *sub_messages[3:]]
        )
        spec.steps[0]["status"] = "done"
        spec.steps[1]["status"] = "done"
        spec.steps[2]["status"] = "failed" if error else "done"
        spec.steps[3]["status"] = "failed" if error else "done"
        spec.progress_pct = 100 if not error else spec.progress_pct
        spec.last_report = final_summary or error
        self.team_obj.setdefault("reports", {})[spec.id] = spec.last_report
        spec.thinking = (
            error
            or f"已返回执行报告，共执行 {len(executed_tool_records)} 次工具操作；由主代理验收。"
        )
        spec.updated_at = now()

        await emit_event("subagent_progress", spec.to_progress_event_dict())
        await emit_event("team", self.get_team_event_data())

        report_payload = {
            "status": spec.status,
            "error": error or None,
            "verification": evaluate_report(final_summary, visible_receipts),
            "model_steps": model_steps,
            "phase_timings": {
                "startup_seconds": round(startup_seconds, 4),
                "model_seconds": round(sum(step["duration_seconds"] for step in model_steps), 4),
                "tool_seconds": round(tool_seconds, 4),
                "model_requests": len(model_steps),
            },
            "model_recovery": recovery.records,
            "receipts": receipts,
            "subagent_name": spec.name,
            "role": spec.role,
            "summary": final_summary or error,
            "files_touched": list(files_touched),
            "tool_call_count": len(executed_tool_records),
            "tool_receipts": executed_tool_records,
            "acceptance_criteria": acceptance_criteria or [],
        }
        return report_payload
