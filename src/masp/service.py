"""Application services and orchestration. Web and CLI share these through HTTP."""

import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from masp import __version__
from masp.agents import Budget, CompatibleProvider, FixtureProvider, Generation, Runtime
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
from masp.storage import Store, identifier, now
from masp.verification import DockerTool, FixtureTool, ToolAdapter, contract_review
from masp.workspace import (
    Workspace,
    apply_proposal,
    git,
    import_repo,
    init_repo,
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
        self.instance_lock.close()

    def create_project(self, request: ProjectCreate) -> dict[str, Any]:
        key = identifier("project")
        root = self.home / "projects" / key
        root.mkdir(parents=True)
        repo = root / "repository"
        if request.repository:
            import_repo(Path(request.repository), repo)
        else:
            init_repo(repo)
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

    def start_run(self, project_id: str, request: RunCreate) -> dict[str, Any]:
        with self.lock:
            project = self.store.get("project", project_id)
            if any(
                run["project_id"] == project_id and State(run["state"]) not in TERMINAL
                for run in self.store.list("run")
            ):
                raise ValueError("A run is already active for this project")
            if sum(not future.done() for future in self.futures.values()) >= 2:
                raise ValueError("Run quota reached: at most two active runs")
            run_id = identifier("run")
            revision = git(Path(project["repository"]), "rev-parse", "HEAD")
            run: dict[str, Any] = {
                "id": run_id,
                "project_id": project_id,
                "state": State.CREATED.value,
                "control": "running",
                "created_at": now(),
                "updated_at": now(),
                "request": request.model_dump(),
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
                self._execute, run_id, project, request, control
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
        session: dict[str, Any] = {
            "id": identifier("agent"),
            "run_id": run_id,
            "task_id": task_id,
            "role": role,
            "model": result.model,
            "model_version": "provider-reported",
            "state": "SUBMITTED",
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
        for attempt in range(request.max_retries + 1):
            try:
                control.checkpoint()
                self.store.transition("task", key, State.RUNNING)
                self.store.update("task", key, attempt=attempt, workspace=str(workspace))
                role = "coder" if attempt == 0 else "repair"
                context = AgentInput(
                    run_id=run_id,
                    task_id=task.id,
                    project_id=project_id,
                    role=role,
                    repository={"commit": base, "branch": f"masp/{run_id}/{task.id}"},
                    contract_version=contract_id,
                    task=task.model_dump(),
                    constraints={"contracts": plan.contracts},
                    context={
                        "attempt": attempt,
                        "failures": failures,
                        "inject_failure": request.inject_failure,
                        "existing": repository_context(workspace, task.allowed_paths),
                        "diff": git(workspace, "diff", "HEAD")[:30000],
                    },
                )
                self.store.event(run_id, "agent.started", {"role": role, "attempt": attempt}, key)
                proposal, generation = runtime.code(context)
                self._generation(run_id, key, role, generation)
                control.checkpoint()
                self.store.transition("task", key, State.REVIEWING)
                findings = contract_review(task, proposal)
                if not findings:
                    review, generation = runtime.review(context, proposal.files)
                    self._generation(run_id, key, "reviewer", generation)
                    findings.extend(review.findings)
                self.store.event(
                    run_id,
                    "review.created",
                    {"findings": [item.model_dump() for item in findings]},
                    key,
                )
                self.store.update("task", key, findings=[item.model_dump() for item in findings])
                results: list[dict[str, Any]] = []
                if not any(item.blocking for item in findings):
                    changed = apply_proposal(workspace, task, proposal)
                    git(workspace, "add", "--all")
                    self.store.update("task", key, changed_files=changed, summary=proposal.summary)
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
        self, run_id: str, project: dict[str, Any], request: RunCreate, control: Control
    ) -> None:
        started = time.monotonic()
        budget = Budget(request.max_tokens)
        runtime = Runtime(
            FixtureProvider() if project["provider"] == "fixture" else CompatibleProvider(), budget
        )
        tool: ToolAdapter = FixtureTool() if project["provider"] == "fixture" else DockerTool()
        try:
            control.checkpoint()
            self.store.transition("run", run_id, State.PLANNING)
            repo = Path(project["repository"])
            plan, generation = runtime.plan(request.requirement, repository_context(repo))
            self._generation(run_id, None, "planner", generation)
            self.store.event(run_id, "plan.generated", plan.model_dump())
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
            manager = Workspace(
                repo,
                self.home / "workspaces" / run_id,
                run_id,
                self.store.get("run", run_id)["repository_revision"],
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
            with ThreadPoolExecutor(
                max_workers=request.max_agents, thread_name_prefix="masp-coder"
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
                        request.max_agents - len(active),
                    )
                    for task in selected:
                        path = manager.task(task.id)
                        self.store.event(
                            run_id, "workspace.created", {"path": str(path)}, f"{run_id}:{task.id}"
                        )
                        states[task.id] = State.RUNNING.value
                        future = executor.submit(
                            self._task,
                            run_id,
                            project["id"],
                            task,
                            plan,
                            path,
                            contract["id"],
                            runtime,
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
                            self.store.event(run_id, "merge.started", {"commit": commit}, key)
                            merged = manager.merge(commit)
                            self.store.event(run_id, "merge.completed", {"commit": merged}, key)
                            self.store.transition("task", key, State.SUCCEEDED)
                            self.store.event(run_id, "task.completed", {"commit": commit}, key)
                        states[task_id] = self.store.get("task", key)["state"]
            control.checkpoint()
            if any(state != State.SUCCEEDED for state in states.values()):
                self.store.transition("run", run_id, State.HUMAN_REVIEW_REQUIRED)
                self.store.update("run", run_id, error="One or more tasks need human review")
                return
            self.store.transition("run", run_id, State.INTEGRATING)
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
                raise ValueError("GIT_CONFLICT: project changed during run; merge withheld")
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
        return {
            "version": __version__,
            "docker_available": shutil.which("docker") is not None,
            "providers": ["fixture", "openai-compatible"],
            "max_agents": 4,
            "fixture_notice": "Fixed arithmetic benchmark; no arbitrary generated code execution",
        }
