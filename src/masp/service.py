"""Application services and orchestration. Web and CLI share these through HTTP."""

import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from masp import __version__
from masp.agents import (
    Budget,
    CompatibleProvider,
    FixtureProvider,
    Generation,
    ModelProvider,
    Runtime,
)
from masp.code_review import run_open_code_review
from masp.contracts import ready, register
from masp.domain import (
    TERMINAL,
    AgentInput,
    Check,
    Plan,
    ProjectCreate,
    RunCreate,
    State,
    TaskSpec,
)
from masp.lock import InstanceLock
from masp.model_settings import load_config
from masp.review_policy import review_reasons
from masp.storage import Store, identifier, now
from masp.verification import DockerTool, FixtureTool, LocalTool, ToolAdapter, contract_review
from masp.workspace import (
    Workspace,
    apply_proposal,
    collect_tool_edits,
    git,
    import_repo,
    init_repo,
    initialize_existing_repo,
    is_repository_root,
    repository_context,
)


@dataclass
class Control:
    cancel: threading.Event = field(default_factory=threading.Event)
    pause: threading.Event = field(default_factory=threading.Event)
    deadline: float = 0

    def stopped(self) -> bool:
        return self.cancel.is_set() or time.monotonic() >= self.deadline

    def checkpoint(self) -> None:
        while self.pause.is_set() and not self.stopped():
            time.sleep(0.05)
        if self.stopped():
            raise InterruptedError("CANCELLED" if self.cancel.is_set() else "TIMEOUT")


class Service:
    def __init__(self, home: Path):
        self.home = home.resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.instance_lock = InstanceLock(self.home / "server.lock")
        self.store = Store(self.home / "store.sqlite3")
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="masp-run")
        self.controls: dict[str, Control] = {}
        self.futures: dict[str, Future[None]] = {}
        self.lock = threading.RLock()
        for build in self.store.list("extension_build"):
            if build.get("status") == "running":
                self.store.update(
                    "extension_build",
                    build["id"],
                    status="interrupted",
                    error="Backend restarted during build; operation was not replayed",
                )
        # A restarted process cannot prove unfinished tool/agent work succeeded.
        for run in self.store.list("run"):
            if State(run["state"]) not in TERMINAL:
                self.store.transition("run", run["id"], State.HUMAN_REVIEW_REQUIRED)
                self.store.update(
                    "run",
                    run["id"],
                    error="Interrupted server; inspect and retry",
                    completed_at=now(),
                )
                self.store.event(run["id"], "run.interrupted", {"reason": "server restart"})
                for task in self.store.list("task", run["id"]):
                    if State(task["state"]) not in TERMINAL:
                        self.store.transition("task", task["id"], State.CANCELLED)

    def close(self) -> None:
        for control in self.controls.values():
            control.cancel.set()
        self.pool.shutdown(wait=True, cancel_futures=False)
        from masp.cordis_runtime import close_native_hosts

        close_native_hosts(self.store)
        self.instance_lock.close()
        self.store.close()

    def create_project(self, request: ProjectCreate) -> dict[str, Any]:
        from masp.plugin_tools import get_dsh_settings

        dsh_cfg = get_dsh_settings(self.store)
        default_branch = (
            str(
                (dsh_cfg.get("workspace") or {}).get("defaultBranch")
                or (dsh_cfg.get("general") or {}).get("defaultBranch")
                or dsh_cfg.get("defaultBranch")
                or "main"
            ).strip()
            or "main"
        )
        key = identifier("project")
        root = self.home / "projects" / key
        root.mkdir(parents=True)
        repo = root / "repository"
        if request.repository:
            source = Path(request.repository).expanduser().resolve(strict=True)
            if not source.is_dir():
                raise ValueError("所选路径必须是文件夹")
            if request.link_repository:
                if not is_repository_root(source):
                    initialize_existing_repo(source, default_branch=default_branch)
                repo = source
            else:
                import_repo(source, repo, default_branch=default_branch)
        else:
            init_repo(repo, default_branch=default_branch)
        return self.store.put(
            "project",
            {
                "id": key,
                "name": request.name,
                "description": request.description,
                "language": request.language,
                "provider": request.provider,
                "repository": str(repo),
                "source_repository": request.repository,
                "created_at": now(),
                "state": "READY",
            },
        )

    def start_run(
        self,
        project_id: str,
        request: RunCreate,
        team: dict[str, Any] | None = None,
        previous_run_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            project = self.store.get("project", project_id)
            if previous_run_id:
                previous = self.store.get("run", previous_run_id)
                if previous["project_id"] != project_id or State(previous["state"]) not in TERMINAL:
                    raise ValueError("上一轮运行必须属于本项目且已经结束")
            if any(
                run["project_id"] == project_id and State(run["state"]) not in TERMINAL
                for run in self.store.list("run")
            ):
                raise ValueError("A run is already active for this project")
            if sum(not future.done() for future in self.futures.values()) >= 2:
                raise ValueError("Run quota reached: at most two active runs")
            run_id = identifier("run")
            repo_path = Path(project["repository"])
            if project.get("provider") != "fixture" and git(repo_path, "status", "--porcelain"):
                try:
                    git(repo_path, "add", "--all")
                    git(
                        repo_path,
                        "commit",
                        "--allow-empty",
                        "-m",
                        "chore: snapshot workspace before run",
                    )
                except Exception:
                    pass
            revision = git(repo_path, "rev-parse", "HEAD")
            resolved_conv_id = (
                conversation_id
                or request.conversation_id
                or (team.get("conversation_id") if isinstance(team, dict) else None)
            )
            run: dict[str, Any] = {
                "id": run_id,
                "project_id": project_id,
                "conversation_id": resolved_conv_id,
                "state": State.CREATED.value,
                "control": "running",
                "created_at": now(),
                "updated_at": now(),
                "request": request.model_dump(),
                "team": team,
                "previous_run_id": previous_run_id,
                "repository_revision": revision,
                "platform_version": __version__,
                "prompt_version": "1.0",
                "plan": None,
                "contract_id": None,
                "artifact_id": None,
                "error": None,
                "metrics": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "repair_count": 0,
                    "duration_ms": 0,
                    "estimated_cost": None,
                },
                "final_checks": [],
            }
            self.store.put("run", run, project_id)
            self.store.update("project", project_id, state=State.RUNNING.value)
            control = Control(deadline=time.monotonic() + request.max_runtime)
            self.controls[run_id] = control
            self.store.event(
                run_id,
                "run.created",
                {"request": request.model_dump(), "repository_revision": revision},
            )
            self.futures[run_id] = self.pool.submit(
                self._execute, run_id, project, request, control, team
            )
            return run

    def control(self, run_id: str, action: str) -> dict[str, Any]:
        with self.lock:
            run = self.store.get("run", run_id)
            if State(run["state"]) in TERMINAL or run_id not in self.controls:
                raise ValueError("Run is terminal; create a retry instead")
            control = self.controls[run_id]
            if action == "cancel":
                control.cancel.set()
            elif action == "pause":
                control.pause.set()
            elif action == "resume":
                control.pause.clear()
            else:
                raise ValueError("Unknown control")
            self.store.event(run_id, f"human.{action}", {})
            self.store.update(
                "project",
                run["project_id"],
                state={
                    "pause": State.PAUSED.value,
                    "resume": State.RUNNING.value,
                    "cancel": State.RUNNING.value,
                }[action],
            )
            return self.store.update(
                "run",
                run_id,
                control={"pause": "paused", "resume": "running", "cancel": "cancelling"}[action],
            )

    def snapshot(self, run_id: str) -> dict[str, Any]:
        run = self.store.get("run", run_id)
        run["tasks"] = self.store.list("task", run_id)
        run["agents"] = self.store.list("session", run_id)
        run["display_state"] = (
            "PAUSED"
            if run["control"] == "paused" and State(run["state"]) not in TERMINAL
            else run["state"]
        )
        return run

    def _generation(self, run_id: str, task_id: str | None, role: str, result: Generation) -> None:
        existing = next(
            (
                item
                for item in self.store.list("session", run_id)
                if item.get("role") == role and item.get("model") == result.model
            ),
            None,
        )
        if existing:
            session = self.store.update(
                "session",
                existing["id"],
                task_id=task_id or existing.get("task_id"),
                state="SUCCEEDED",
                input_tokens=int(existing.get("input_tokens") or 0) + int(result.input_tokens or 0),
                output_tokens=int(existing.get("output_tokens") or 0)
                + int(result.output_tokens or 0),
                latency_ms=int(existing.get("latency_ms") or 0) + int(result.latency_ms or 0),
            )
        else:
            session = {
                "id": identifier("agent"),
                "run_id": run_id,
                "task_id": task_id,
                "role": role,
                "model": result.model,
                "model_version": "provider-reported",
                "state": "SUCCEEDED",
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
                "prompt_version": "1.0",
                "created_at": now(),
            }
            self.store.put("session", session, run_id)
        self.store.event(run_id, "agent.completed", session, task_id, session["id"])

    def _checks(
        self,
        run_id: str,
        task_id: str | None,
        root: Path,
        checks: list[Check],
        tool: ToolAdapter,
        control: Control,
    ) -> list[dict[str, Any]]:
        results = []
        layers = ("contract", "build", "lint", "type", "unit", "integration", "security")
        for check in sorted(checks, key=lambda item: layers.index(item.layer)):
            control.checkpoint()
            self.store.event(
                run_id,
                "agent.tool_call",
                {"tool": type(tool).__name__, "command": check.command, "workspace": str(root)},
                task_id,
            )
            self.store.event(run_id, "verification.started", check.model_dump(), task_id)
            result = tool.execute(root, check, control.stopped).model_dump()
            results.append(result)
            self.store.event(run_id, "tool.completed", result, task_id)
            self.store.event(run_id, "verification.completed", result, task_id)
            if result["status"] != "passed":
                break
        return results

    def _task(
        self,
        run_id: str,
        project_id: str,
        task: TaskSpec,
        plan: Plan,
        workspace: Path,
        contract_id: str,
        runtime: Runtime,
        tool: ToolAdapter,
        control: Control,
        request: RunCreate,
        manager: Workspace,
    ) -> str | None:
        key = f"{run_id}:{task.id}"
        failures: list[dict[str, Any]] = []
        base = git(workspace, "rev-parse", "HEAD")
        team = self.store.get("run", run_id).get("team") or {}
        ocr_enabled = team.get("review_mode") == "open-code-review"
        adaptive_review = team.get("review_mode", "adaptive") == "adaptive"
        dependency_scopes = [
            scope
            for upstream in plan.tasks
            if upstream.id in task.dependencies
            for scope in upstream.allowed_paths
        ]
        reviewer_profile = team.get("review_profile_id")
        review_runtime = (
            Runtime(
                CompatibleProvider(
                    load_config(self.store, self.home, reviewer_profile),
                    self.store,
                    self.home,
                    checkpoint=control.checkpoint,
                ),
                runtime.budget,
            )
            if reviewer_profile and not ocr_enabled
            else runtime
        )
        for attempt in range(request.max_retries + 1):
            try:
                control.checkpoint()
                self.store.transition("task", key, State.RUNNING)
                self.store.update("task", key, attempt=attempt, workspace=str(workspace))
                role = task.agent_id or ("coder" if attempt == 0 else "repair")
                context = AgentInput(
                    run_id=run_id,
                    task_id=task.id,
                    project_id=project_id,
                    role=role,
                    repository={"commit": base, "branch": f"masp/{run_id}/{task.id}"},
                    contract_version=contract_id,
                    task=task.model_dump(),
                    constraints={
                        "contracts": plan.contracts,
                        "shared_principles": plan.architecture.get("shared_principles", []),
                    },
                    context={
                        "attempt": attempt,
                        "failures": failures,
                        "inject_failure": request.inject_failure,
                        "existing": repository_context(
                            workspace, task.allowed_paths + dependency_scopes
                        ),
                        "workspace": str(workspace),
                        "diff": git(workspace, "diff", "HEAD")[:30000],
                    },
                )
                self.store.event(run_id, "agent.started", {"role": role, "attempt": attempt}, key)
                proposal, generation = runtime.code(context)
                is_real_ocr = ocr_enabled and not isinstance(runtime.provider, FixtureProvider)
                if is_real_ocr:
                    extra_names = set(git(workspace, "diff", base, "--name-only", "-z").split("\0"))
                    extra_names.update(
                        git(workspace, "ls-files", "--others", "--exclude-standard", "-z").split(
                            "\0"
                        )
                    )
                    extra_names.update(proposal.files.keys())
                    for extra in sorted(extra_names - {""}):
                        if extra not in task.allowed_paths:
                            task.allowed_paths.append(extra)
                # Actual files edited by tools must not bypass structured review.
                tool_edits = collect_tool_edits(workspace, task, base)
                proposal = type(proposal).model_validate(
                    {
                        **proposal.model_dump(),
                        "files": {**tool_edits, **proposal.files},
                    }
                )
                self._generation(run_id, key, role, generation)
                control.checkpoint()
                self.store.transition("task", key, State.REVIEWING)
                findings = contract_review(task, proposal)
                risk_paths = review_reasons(proposal.files) if adaptive_review else []
                self.store.event(
                    run_id,
                    "review.policy",
                    {
                        "mode": team.get("review_mode", "adaptive"),
                        "independent_review": ocr_enabled or bool(risk_paths),
                        "risk_paths": risk_paths,
                    },
                    key,
                )
                if not findings and adaptive_review and risk_paths:
                    review, generation = review_runtime.review(context, proposal.files)
                    self._generation(run_id, key, "reviewer", generation)
                    findings.extend(review.findings)
                if (
                    not findings
                    and not ocr_enabled
                    and isinstance(runtime.provider, FixtureProvider)
                ):
                    review, generation = review_runtime.review(context, proposal.files)
                    self._generation(run_id, key, "reviewer", generation)
                    findings.extend(review.findings)
                results: list[dict[str, Any]] = []
                if not any(item.blocking for item in findings):
                    changed = apply_proposal(workspace, task, proposal)
                    git(workspace, "add", "--all")
                    self.store.update("task", key, changed_files=changed, summary=proposal.summary)
                    if ocr_enabled:
                        control.checkpoint()
                        review_config = load_config(
                            self.store,
                            self.home,
                            reviewer_profile or team["main_profile_id"],
                        )
                        try:
                            ocr_findings, report = run_open_code_review(workspace, review_config)
                            findings.extend(ocr_findings)
                            self.store.event(run_id, "review.external", report, key)
                        except (RuntimeError, ValueError) as ocr_err:
                            self.store.event(
                                run_id,
                                "review.external",
                                {
                                    "engine": "open-code-review",
                                    "status": "fallback",
                                    "model": review_config.model,
                                    "error": str(ocr_err),
                                },
                                key,
                            )
                self.store.event(
                    run_id,
                    "review.created",
                    {"findings": [item.model_dump() for item in findings]},
                    key,
                )
                self.store.update("task", key, findings=[item.model_dump() for item in findings])
                if not any(item.blocking for item in findings):
                    self.store.transition("task", key, State.VERIFYING)
                    results = self._checks(run_id, key, workspace, task.checks, tool, control)
                attempt_record = {
                    "attempt": attempt,
                    "findings": [f.model_dump() for f in findings],
                    "checks": results,
                    "timestamp": now(),
                }
                failures.append(attempt_record)
                self.store.update(
                    "task", key, attempts=failures, diff=git(workspace, "diff", "HEAD")[:100000]
                )
                control.checkpoint()
                if (
                    results
                    and all(item["status"] == "passed" for item in results)
                    and not any(item.blocking for item in findings)
                ):
                    collect_tool_edits(workspace, task, base)
                    self.store.transition("task", key, State.INTEGRATING)
                    commit = manager.commit(workspace, task.id)
                    self.store.update("task", key, commit=commit, error=None)
                    if attempt:
                        self.store.event(run_id, "repair.completed", {"attempt": attempt}, key)
                    return commit
                if any(item.get("error_type") == "SECURITY_BLOCK" for item in results):
                    raise PermissionError("SECURITY_BLOCK: sandbox unavailable")
                if attempt < request.max_retries:
                    self.store.transition("task", key, State.REPAIRING)
                    self.store.event(
                        run_id,
                        "repair.started",
                        {"attempt": attempt + 1, "evidence": attempt_record},
                        key,
                    )
                else:
                    self.store.transition("task", key, State.HUMAN_REVIEW_REQUIRED)
            except InterruptedError:
                self.store.transition("task", key, State.CANCELLED)
                return None
            except Exception as error:
                self.store.event(run_id, "task.error", {"error": str(error)}, key)
                self.store.update("task", key, error=str(error))
                current = State(self.store.get("task", key)["state"])
                if (
                    attempt < request.max_retries
                    and not isinstance(error, PermissionError)
                    and current in {State.RUNNING, State.REVIEWING, State.VERIFYING}
                ):
                    failures.append({"attempt": attempt, "error": str(error), "checks": []})
                    self.store.update("task", key, attempts=failures)
                    self.store.transition("task", key, State.REPAIRING)
                    self.store.event(
                        run_id, "repair.started", {"attempt": attempt + 1, "error": str(error)}, key
                    )
                    continue
                self.store.transition("task", key, State.HUMAN_REVIEW_REQUIRED)
                return None
        return None

    def _execute(
        self,
        run_id: str,
        project: dict[str, Any],
        request: RunCreate,
        control: Control,
        team: dict[str, Any] | None = None,
    ) -> None:
        started = time.monotonic()
        budget = Budget(request.max_tokens)
        provider: ModelProvider
        if project["provider"] == "fixture":
            provider = FixtureProvider()
        elif team:
            provider = CompatibleProvider(
                load_config(self.store, self.home, team["main_profile_id"]),
                self.store,
                self.home,
                checkpoint=control.checkpoint,
            )
        else:
            provider = CompatibleProvider(
                store=self.store, home=self.home, checkpoint=control.checkpoint
            )
        runtime = Runtime(provider, budget)
        tool: ToolAdapter = (
            FixtureTool()
            if project["provider"] == "fixture"
            else LocalTool()
            if request.execution_mode == "local"
            else DockerTool()
        )
        try:
            control.checkpoint()
            self.store.transition("run", run_id, State.PLANNING)
            repo = Path(project["repository"])
            context = repository_context(repo)
            if team:
                context["team"] = team
            previous_id = self.store.get("run", run_id).get("previous_run_id")
            if previous_id:
                previous = self.snapshot(previous_id)
                context["previous_round"] = {
                    "requirement": previous["request"]["requirement"],
                    "state": previous["state"],
                    "plan": previous["plan"],
                    "tasks": [
                        {
                            "id": task["spec"]["id"],
                            "title": task["spec"]["title"],
                            "agent_id": task["spec"].get("agent_id"),
                            "allowed_paths": task["spec"]["allowed_paths"],
                            "state": task["state"],
                        }
                        for task in previous["tasks"]
                    ],
                    "error": previous.get("error"),
                }
            plan, generation = runtime.plan(request.requirement, context)
            members = {agent["id"]: agent for agent in team["agents"]} if team else {}
            if team:
                for spec in plan.tasks:
                    if spec.agent_id not in members:
                        raise ValueError(
                            f"Task {spec.id} has no valid team agent; planning must assign agent_id"
                        )
                    owned = members[spec.agent_id]["owned_paths"]
                    if owned and any(
                        not any(
                            path == root or path.startswith(root.rstrip("/") + "/")
                            for root in owned
                        )
                        for path in spec.allowed_paths
                    ):
                        raise ValueError(
                            f"Task {spec.id} changes paths outside agent {spec.agent_id} ownership"
                        )
            self._generation(run_id, None, "planner", generation)
            self.store.event(run_id, "plan.generated", plan.model_dump())
            self.store.event(
                run_id,
                "plan.principles",
                {
                    "shared_principles": plan.architecture.get("shared_principles", []),
                    "contracts": plan.contracts,
                },
            )
            control.checkpoint()
            self.store.transition("run", run_id, State.CONTRACTING)
            contract = register(self.store, project["id"], run_id, plan)
            self.store.update("run", run_id, plan=plan.model_dump(), contract_id=contract["id"])
            if contract["potentially_breaking"]:
                if not request.approve_contract_change:
                    self.store.transition("run", run_id, State.HUMAN_REVIEW_REQUIRED)
                    self.store.update(
                        "run",
                        run_id,
                        error="CONTRACT_ERROR: shared interfaces changed; "
                        "inspect contract diff and approve explicitly on a new run",
                    )
                    return
                self.store.event(run_id, "human.contract_override", {"contract_id": contract["id"]})
            from masp.plugin_tools import get_dsh_settings

            dsh_cfg = get_dsh_settings(self.store)
            isolate_wt = bool((dsh_cfg.get("subagent") or {}).get("isolateWorktree", True))
            manager = Workspace(
                repo,
                self.home / "workspaces" / run_id,
                run_id,
                self.store.get("run", run_id)["repository_revision"],
                isolate_worktree=isolate_wt,
            )
            manager.create()
            self.store.event(
                run_id,
                "workspace.created",
                {"path": str(manager.integration), "branch": manager.branch},
            )
            self.store.transition("run", run_id, State.SCHEDULING)
            for spec in plan.tasks:
                key = f"{run_id}:{spec.id}"
                self.store.put(
                    "task",
                    {
                        "id": key,
                        "spec_id": spec.id,
                        "run_id": run_id,
                        "state": State.QUEUED.value,
                        "spec": spec.model_dump(),
                        "attempt": 0,
                        "attempts": [],
                        "findings": [],
                        "changed_files": [],
                        "commit": None,
                        "diff": "",
                        "error": None,
                        "created_at": now(),
                    },
                    run_id,
                )
                self.store.event(run_id, "task.queued", {"spec": spec.model_dump()}, key)
            self.store.transition("run", run_id, State.RUNNING)
            states = {task.id: State.QUEUED.value for task in plan.tasks}
            by_id = {task.id: task for task in plan.tasks}
            # Launch all independent sub-agents concurrently in parallel
            parallel_slots = request.max_agents
            completed_commits: list[tuple[str, str]] = []
            integration_started = False
            with ThreadPoolExecutor(
                max_workers=parallel_slots, thread_name_prefix="masp-coder"
            ) as executor:
                active: dict[Future[str | None], str] = {}
                while any(State(state) not in TERMINAL for state in states.values()):
                    control.checkpoint()
                    for task in plan.tasks:
                        if states[task.id] == State.QUEUED and any(
                            State(states[dep]) in TERMINAL and states[dep] != State.SUCCEEDED
                            for dep in task.dependencies
                        ):
                            states[task.id] = State.BLOCKED.value
                            self.store.transition("task", f"{run_id}:{task.id}", State.BLOCKED)
                    selected = ready(
                        plan.tasks,
                        states,
                        [by_id[key] for key in active.values()],
                        parallel_slots - len(active),
                    )
                    for task in selected:
                        path = manager.task(task.id)
                        self.store.event(
                            run_id, "workspace.created", {"path": str(path)}, f"{run_id}:{task.id}"
                        )
                        states[task.id] = State.RUNNING.value
                        task_runtime = runtime
                        if team:
                            profile_id = (
                                members[task.agent_id]["model_profile_id"]
                                or team["main_profile_id"]
                            )
                            task_runtime = Runtime(
                                CompatibleProvider(
                                    load_config(self.store, self.home, profile_id),
                                    self.store,
                                    self.home,
                                    checkpoint=control.checkpoint,
                                ),
                                budget,
                            )
                        future = executor.submit(
                            self._task,
                            run_id,
                            project["id"],
                            task,
                            plan,
                            path,
                            contract["id"],
                            task_runtime,
                            tool,
                            control,
                            request,
                            manager,
                        )
                        active[future] = task.id
                    if not active:
                        break
                    done, _ = wait(active, timeout=0.1, return_when=FIRST_COMPLETED)
                    for future in done:
                        task_id = active.pop(future)
                        key = f"{run_id}:{task_id}"
                        commit = future.result()
                        control.checkpoint()
                        if commit:
                            if not integration_started:
                                self.store.event(
                                    run_id,
                                    "main.merge.started",
                                    {"tasks": [task.id for task in plan.tasks]},
                                )
                                integration_started = True
                            self.store.event(run_id, "merge.started", {"commit": commit}, key)
                            merged = manager.merge(commit)
                            self.store.event(run_id, "merge.completed", {"commit": merged}, key)
                            self.store.transition("task", key, State.SUCCEEDED)
                            self.store.event(run_id, "task.completed", {"commit": commit}, key)
                            completed_commits.append((task_id, commit))
                            states[task_id] = State.SUCCEEDED.value
                        else:
                            states[task_id] = self.store.get("task", key)["state"]
            control.checkpoint()
            if any(state != State.SUCCEEDED for state in states.values()):
                self.store.transition("run", run_id, State.HUMAN_REVIEW_REQUIRED)
                self.store.update("run", run_id, error="One or more tasks need human review")
                return
            self.store.transition("run", run_id, State.INTEGRATING)
            # Unified Review Agent inspection + Main Agent merge across all parallel sub-agents
            if project["provider"] != "fixture":
                reviewer_profile = (team or {}).get("review_profile_id") or (team or {}).get(
                    "main_profile_id"
                )
                unified_review_runtime = (
                    Runtime(
                        CompatibleProvider(
                            load_config(self.store, self.home, reviewer_profile),
                            self.store,
                            self.home,
                            checkpoint=control.checkpoint,
                        ),
                        budget,
                    )
                    if reviewer_profile
                    else runtime
                )
                combined_files: dict[str, str] = {}
                for task_id, _ in completed_commits:
                    t_ws = self.home / "workspaces" / run_id / task_id
                    for rel_p in by_id[task_id].allowed_paths:
                        cand = t_ws / rel_p
                        if cand.is_file():
                            combined_files[rel_p] = cand.read_text(
                                encoding="utf-8", errors="replace"
                            )[:12000]
                if combined_files and (team or {}).get("review_mode") == "internal":
                    try:
                        review_ctx = AgentInput(
                            run_id=run_id,
                            task_id="unified_review",
                            project_id=project["id"],
                            role="reviewer",
                            repository={"commit": manager.revision, "branch": manager.branch},
                            contract_version=contract["id"],
                            task={"id": "unified_review", "allowed_paths": list(combined_files)},
                            constraints={
                                "contracts": plan.contracts,
                                "shared_principles": plan.architecture.get("shared_principles", []),
                            },
                            context={"attempt": 0},
                        )
                        uni_review, uni_gen = unified_review_runtime.review(
                            review_ctx, combined_files
                        )
                        self._generation(run_id, None, "reviewer", uni_gen)
                        self.store.event(
                            run_id,
                            "review.unified",
                            {"findings": [f.model_dump() for f in uni_review.findings]},
                        )
                        if any(f.blocking for f in uni_review.findings):
                            self.store.transition("run", run_id, State.HUMAN_REVIEW_REQUIRED)
                            self.store.update(
                                "run",
                                run_id,
                                error="Independent integration review rejected changes",
                            )
                            return
                    except Exception as error:
                        self.store.transition("run", run_id, State.HUMAN_REVIEW_REQUIRED)
                        self.store.update(
                            "run",
                            run_id,
                            error=f"Integration review failed: {type(error).__name__}",
                        )
                        return
            self.store.event(
                run_id,
                "main.merge.completed",
                {"commit": git(manager.integration, "rev-parse", "HEAD")},
            )
            self.store.transition("run", run_id, State.FINAL_VERIFY)
            results = self._checks(
                run_id, None, manager.integration, plan.final_checks, tool, control
            )
            self.store.update("run", run_id, final_checks=results, diff=manager.diff())
            control.checkpoint()
            if not results or any(result["status"] != "passed" for result in results):
                self.store.transition("run", run_id, State.FAILED)
                self.store.update("run", run_id, error="Final verification rejected integration")
                return
            commit = git(manager.integration, "rev-parse", "HEAD")
            if git(repo, "rev-parse", "HEAD") != manager.revision or git(
                repo, "status", "--porcelain"
            ):
                raise ValueError(
                    "GIT_CONFLICT: project changed during run; integration retained for review"
                )
            else:
                git(repo, "merge", "--ff-only", commit)
            artifact_id = identifier("artifact")
            archive = self.home / "artifacts" / f"{artifact_id}.zip"
            archive.parent.mkdir(exist_ok=True)
            git(manager.integration, "archive", "--format=zip", f"--output={archive}", "HEAD")
            self.store.put(
                "artifact",
                {
                    "id": artifact_id,
                    "project_id": project["id"],
                    "run_id": run_id,
                    "path": str(archive),
                    "commit": commit,
                    "branch": manager.branch,
                    "created_at": now(),
                },
                project["id"],
            )
            self.store.update(
                "run",
                run_id,
                artifact_id=artifact_id,
                commit=commit,
                integration_branch=manager.branch,
            )
            self.store.transition("run", run_id, State.SUCCEEDED)
        except InterruptedError as error:
            self.store.transition(
                "run", run_id, State.CANCELLED if control.cancel.is_set() else State.FAILED
            )
            self.store.update("run", run_id, error=str(error))
        except Exception as error:
            run = self.store.get("run", run_id)
            if State(run["state"]) not in TERMINAL:
                self.store.transition("run", run_id, State.FAILED)
            self.store.update("run", run_id, error=str(error))
            self.store.event(run_id, "run.error", {"error": str(error)})
        finally:
            run = self.store.get("run", run_id)
            for task_record in self.store.list("task", run_id):
                if State(task_record["state"]) not in TERMINAL:
                    self.store.transition("task", task_record["id"], State.CANCELLED)
            repairs = sum(task["attempt"] for task in self.store.list("task", run_id))
            metrics = {
                "input_tokens": budget.input_tokens,
                "output_tokens": budget.output_tokens,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "repair_count": repairs,
                "estimated_cost": None,
            }
            self.store.update("run", run_id, metrics=metrics, completed_at=now())
            project_runs = [
                item for item in self.store.list("run", run["project_id"]) if item["id"] != run_id
            ]
            active_project_run = any(State(item["state"]) not in TERMINAL for item in project_runs)
            project_state = (
                State.RUNNING.value
                if active_project_run
                else (
                    State.SUCCEEDED.value
                    if run["state"] == State.SUCCEEDED.value
                    else State.CANCELLED.value
                    if run["state"] == State.CANCELLED.value
                    else State.FAILED.value
                )
            )
            self.store.update("project", run["project_id"], state=project_state)
            self.store.event(run_id, "project.state", {"state": project_state})
            self.store.event(run_id, "run.completed", {"state": run["state"], "metrics": metrics})

    def capabilities(self) -> dict[str, Any]:
        from masp.code_review import ocr_engine_status

        return {
            "version": __version__,
            "build_id": "2026-10-04-v22-plugin-websocket",
            "builtin_mcp_ready": True,
            "open_code_review": ocr_engine_status(),
            "docker_available": shutil.which("docker") is not None,
            "providers": ["fixture", "openai-compatible"],
            "max_agents": 64,
            "fixture_notice": "Fixed arithmetic benchmark; no arbitrary generated code execution",
        }
