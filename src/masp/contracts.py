"""Versioned contract registration, structural diff, and deterministic task selection."""

import hashlib
import json
from typing import Any

from masp.domain import Plan, State, TaskSpec
from masp.storage import Store, identifier, now


def register(store: Store, project_id: str, run_id: str, plan: Plan) -> dict[str, Any]:
    prior = store.list("contract", project_id)
    document = plan.model_dump()
    digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
    previous = prior[0]["plan"] if prior else None
    diff = {"before": previous["contracts"] if previous else [], "after": document["contracts"]}
    # Conservative compatibility policy: any shared-interface change needs review.
    breaking = previous is not None and diff["before"] != diff["after"]
    record = {"id": identifier("contract"), "project_id": project_id, "run_id": run_id,
              "version": len(prior) + 1, "schema_version": "1.0", "digest": digest,
              "created_at": now(), "plan": document, "diff": diff,
              "potentially_breaking": breaking, "validation": "passed"}
    store.put("contract", record, project_id)
    store.event(run_id, "contract.created", {"id": record["id"], "digest": digest,
                                            "version": record["version"]})
    return record


def conflicts(left: TaskSpec, right: TaskSpec) -> bool:
    if set(left.resources) & set(right.resources):
        return True
    for a in left.allowed_paths:
        for b in right.allowed_paths:
            x, y = a.casefold(), b.casefold()
            if x == y or x.startswith(y + "/") or y.startswith(x + "/"):
                return True
    return False


def ready(tasks: list[TaskSpec], states: dict[str, str], running: list[TaskSpec],
          slots: int) -> list[TaskSpec]:
    chosen: list[TaskSpec] = []
    for task in sorted(tasks, key=lambda item: (-item.priority, item.id)):
        if len(chosen) >= slots:
            break
        if states[task.id] != State.QUEUED:
            continue
        if not all(states[dep] == State.SUCCEEDED for dep in task.dependencies):
            continue
        if not any(conflicts(task, other) for other in running + chosen):
            chosen.append(task)
    return chosen
