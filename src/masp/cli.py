"""HTTP client for exactly the same API used by the web application."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="masp", description="Multi-agent engineering workspace")
    parser.add_argument("--url", default="http://127.0.0.1:3080")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start local web application and API")
    serve.add_argument("--port", type=int, default=3080)
    serve.add_argument(
        "--native-patch",
        action="append",
        type=Path,
        default=[],
        help="Native invocation overlay; repeat in precedence order",
    )
    init = sub.add_parser("init", help="Create a managed project or import a local Git repository")
    init.add_argument("name")
    init.add_argument("--repository")
    init.add_argument("--provider", choices=["fixture", "openai-compatible"], default="fixture")
    sub.add_parser("projects")
    run = sub.add_parser("run")
    run.add_argument("project_id")
    run.add_argument("requirement")
    run.add_argument("--inject-failure", action="store_true")
    run.add_argument("--max-agents", type=int, default=2)
    for name in ("inspect", "replay", "logs", "pause", "resume", "cancel", "retry", "verify"):
        sub.add_parser(name).add_argument("run_id")
    for name in ("tasks", "agents", "contracts", "artifacts"):
        sub.add_parser(name).add_argument("project_id")
    sub.add_parser("task").add_argument("task_id")
    sub.add_parser("contract-check").add_argument("path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn

        if args.native_patch:
            os.environ["MICRO_MULTI_NATIVE_PATCHES"] = json.dumps(
                [str(path.resolve()) for path in args.native_patch]
            )
        uvicorn.run("masp.api:create_app", factory=True, host="127.0.0.1", port=args.port)
        return 0
    method, path, body = "GET", "", None
    if args.command == "init":
        method, path = "POST", "/projects"
        body = {"name": args.name, "repository": args.repository, "provider": args.provider}
    elif args.command == "projects":
        path = "/projects"
    elif args.command == "run":
        method, path = "POST", f"/projects/{args.project_id}/runs"
        body = {
            "requirement": args.requirement,
            "inject_failure": args.inject_failure,
            "max_agents": args.max_agents,
        }
    elif args.command in {"pause", "resume", "cancel", "retry"}:
        method, path, body = "POST", f"/runs/{args.run_id}/{args.command}", {}
    elif args.command in {"inspect", "verify"}:
        path = f"/runs/{args.run_id}"
    elif args.command in {"replay", "logs"}:
        path = f"/runs/{args.run_id}/{args.command}"
    elif args.command in {"tasks", "agents", "contracts", "artifacts"}:
        path = f"/projects/{args.project_id}/{args.command}"
    elif args.command == "task":
        path = f"/tasks/{args.task_id}"
    elif args.command == "contract-check":
        method, path = "POST", "/contracts/check"
        body = json.loads(args.path.read_text("utf-8"))
    try:
        response = httpx.request(
            method, args.url.rstrip("/") + "/api" + path, json=body, timeout=60
        )
        response.raise_for_status()
        result: Any = response.json()
        if args.command == "verify":
            result = {"state": result["state"], "checks": result["final_checks"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except httpx.HTTPError as error:
        print(f"API request failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
