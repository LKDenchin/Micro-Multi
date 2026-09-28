"""Local REST API and SSE events, shared by the web application and CLI."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from masp.domain import TERMINAL, Plan, ProjectCreate, RunCreate, State
from masp.service import Service
from masp.workspace import GitError


class LocalRequestGuard:
    """Reject cross-origin writes and DNS rebinding against the loopback app."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            headers = dict(scope["headers"])
            origin = headers.get(b"origin", b"").decode()
            host = headers.get(b"host", b"").decode()
            if origin and urlsplit(origin).netloc != host:
                await JSONResponse({"detail": "Cross-origin writes are forbidden"}, 403)(
                    scope, receive, send
                )
                return
            if headers.get(b"content-type", b"").split(b";")[0] != b"application/json":
                await JSONResponse({"detail": "Use application/json"}, 415)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(home: Path | None = None) -> FastAPI:
    location = home or Path(os.environ.get("MASP_HOME", ".masp"))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.service = Service(location)
        yield
        await asyncio.to_thread(app.state.service.close)

    app = FastAPI(title="MASP Workspace API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(LocalRequestGuard)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
    )

    def service() -> Service:
        return app.state.service

    @app.exception_handler(KeyError)
    async def missing(request: Request, error: KeyError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request: Request, error: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(GitError)
    async def git_failure(request: Request, error: GitError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", **service().capabilities()}

    @app.get("/api/projects")
    def projects() -> list[dict[str, Any]]:
        return service().store.list("project")

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectCreate) -> dict[str, Any]:
        return service().create_project(body)

    @app.get("/api/projects/{project_id}")
    def project(project_id: str) -> dict[str, Any]:
        return service().store.get("project", project_id)

    @app.get("/api/projects/{project_id}/{resource}")
    def project_resource(project_id: str, resource: str) -> list[dict[str, Any]]:
        service().store.get("project", project_id)
        if resource in {"runs", "contracts", "artifacts"}:
            return service().store.list(resource[:-1], project_id)
        if resource in {"tasks", "agents"}:
            return [
                record
                for run in service().store.list("run", project_id)
                for record in service().store.list(
                    "task" if resource == "tasks" else "session", run["id"]
                )
            ]
        raise HTTPException(404, "Unknown project resource")

    @app.post("/api/projects/{project_id}/runs", status_code=202)
    def run(project_id: str, body: RunCreate) -> dict[str, Any]:
        return service().start_run(project_id, body)

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return service().store.list("run")

    @app.get("/api/runs/{run_id}")
    def inspect(run_id: str) -> dict[str, Any]:
        return service().snapshot(run_id)

    @app.get("/api/runs/{run_id}/replay")
    def replay(run_id: str) -> dict[str, Any]:
        return service().snapshot(run_id)

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str, after: int = Query(default=0, ge=0)) -> list[dict[str, Any]]:
        service().store.get("run", run_id)
        return service().store.events(run_id, after)

    @app.get("/api/runs/{run_id}/stream")
    async def stream(
        request: Request, run_id: str, after: int = Query(default=0, ge=0)
    ) -> StreamingResponse:
        service().store.get("run", run_id)
        last = request.headers.get("last-event-id", "0")
        cursor = max(after, int(last) if last.isdigit() else 0)

        async def generate() -> AsyncIterator[str]:
            nonlocal cursor
            while not await request.is_disconnected():
                batch = await asyncio.to_thread(service().store.events, run_id, cursor)
                for event in batch:
                    cursor = event["sequence"]
                    yield f"id: {cursor}\ndata: {json.dumps(event)}\n\n"
                current = await asyncio.to_thread(service().store.get, "run", run_id)
                if (
                    State(current["state"]) in TERMINAL
                    and current.get("completed_at")
                    and not batch
                ):
                    yield "event: complete\ndata: {}\n\n"
                    return
                if not batch:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.4)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/logs")
    def logs(run_id: str, after: int = Query(default=0, ge=0)) -> list[dict[str, Any]]:
        return events(run_id, after)

    @app.post("/api/runs/{run_id}/{action}")
    def control(run_id: str, action: str) -> dict[str, Any]:
        if action == "retry":
            old = service().store.get("run", run_id)
            if State(old["state"]) not in TERMINAL:
                raise ValueError("Only terminal runs can be retried")
            new = service().start_run(old["project_id"], RunCreate.model_validate(old["request"]))
            service().store.event(new["id"], "run.retry", {"previous_run": run_id})
            return new
        return service().control(run_id, action)

    @app.get("/api/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        return service().store.get("task", task_id)

    @app.post("/api/contracts/check")
    def contract_check(body: Plan) -> dict[str, Any]:
        return {"status": "passed", "tasks": len(body.tasks), "version": body.version}

    @app.get("/api/artifacts/{artifact_id}/download")
    def download(artifact_id: str) -> FileResponse:
        artifact = service().store.get("artifact", artifact_id)
        return FileResponse(
            artifact["path"], filename=f"{artifact_id}.zip", media_type="application/zip"
        )

    web = Path(__file__).parent / "web"
    app.mount("/static", StaticFiles(directory=web), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(web / "index.html")

    return app
