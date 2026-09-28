"""Fixed fixture comparison. Report measurements, never infer model performance."""

import argparse
import hashlib
import json
import platform
import tempfile
from pathlib import Path

from masp.agents import fixture_plan
from masp.domain import ProjectCreate, RunCreate
from masp.service import Service
from masp.workspace import git


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--output", type=Path, default=Path("evidence/benchmark.json"))
    args = parser.parse_args()
    rows = []
    with tempfile.TemporaryDirectory(prefix="masp-bench-") as directory:
        service = Service(Path(directory))
        try:
            baseline = service.create_project(ProjectCreate(name="benchmark-baseline"))
            revision = git(Path(baseline["repository"]), "rev-parse", "HEAD")
            for workers in args.workers:
                project = service.create_project(
                    ProjectCreate(name=f"workers-{workers}", repository=baseline["repository"])
                )
                run = service.start_run(
                    project["id"],
                    RunCreate(
                        requirement="Implement signed add and subtract; inject one failing test",
                        max_agents=workers,
                        inject_failure=True,
                    ),
                )
                service.futures[run["id"]].result(timeout=120)
                result = service.snapshot(run["id"])
                rows.append(
                    {
                        "workers": workers,
                        "run_id": run["id"],
                        "state": result["state"],
                        "base_revision": revision,
                        "metrics": result["metrics"],
                    }
                )
        finally:
            service.close()
    report = {
        "benchmark": "arithmetic-fixture-v1",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "plan_sha256": hashlib.sha256(fixture_plan().model_dump_json().encode()).hexdigest(),
        "conditions": "Fixed two-task DAG, one injected defect, no external model calls; "
        "one sample per concurrency, Git overhead included",
        "runs": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if all(row["state"] == "SUCCEEDED" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
