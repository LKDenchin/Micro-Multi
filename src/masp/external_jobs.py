"""Generic MCP external-agent selection and turn-owned background jobs."""

import asyncio
import json
import re
from typing import Any


def select_external_tools(
    schemas: list[dict[str, Any]], lookup: dict[str, Any], request: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # Orchestrators launch another model/process; ordinary MCP tools remain available.
    providers = set()
    for schema in schemas:
        fn = schema["function"]
        server, name = lookup[fn["name"]]
        props = fn.get("parameters", {}).get("properties", {})
        if name in {"start_run", "start_job", "spawn_agent", "run_agent"} and {
            "agent",
            "agentId",
            "agent_id",
        }.intersection(props):
            provider = re.sub(r"[\W_]", "", str(server.get("name", "")).casefold())
            intent = re.sub(r"[\W_]", "", request.casefold())
            if provider and provider not in intent:
                providers.add(server["id"])
    selected = [
        schema for schema in schemas if lookup[schema["function"]["name"]][0]["id"] not in providers
    ]
    return selected, {
        schema["function"]["name"]: lookup[schema["function"]["name"]] for schema in selected
    }


class ExternalJobs:
    """Only clean up jobs actually launched by this turn, never discovered jobs."""

    def __init__(self, lookup: dict[str, Any]):
        self.lookup = lookup
        self.jobs: dict[tuple[str, str], tuple[dict[str, Any], str, str]] = {}

    def observe(self, server: dict[str, Any], name: str, arguments: str, result: str) -> None:
        try:
            data = json.loads(result)
            if isinstance(data, str):
                data = json.loads(data)
            args = json.loads(arguments)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict) or not isinstance(args, dict):
            return
        job_id = (
            data.get("runId")
            or data.get("jobId")
            or data.get("id")
            or args.get("runId")
            or args.get("jobId")
        )
        if not isinstance(job_id, str):
            return
        key = (server["id"], job_id)
        status = data.get("status")
        if status in {"succeeded", "completed", "failed", "canceled", "cancelled"}:
            self.jobs.pop(key, None)
            return
        if name not in {"start_run", "start_job"} or status not in {"queued", "running", "pending"}:
            return
        cancel_name = name.replace("start_", "cancel_", 1)
        for candidate_server, candidate_name in self.lookup.values():
            if candidate_server["id"] == server["id"] and candidate_name == cancel_name:
                self.jobs[key] = (server, cancel_name, "runId" if name == "start_run" else "jobId")
                break

    async def close(self, invoke: Any) -> list[dict[str, str]]:
        async def cancel(
            key: tuple[str, str], job: tuple[dict[str, Any], str, str]
        ) -> dict[str, str]:
            server, name, field = job
            try:
                response = await asyncio.wait_for(
                    invoke(server, name, json.dumps({field: key[1]})), 10
                )
                if str(response).startswith("MCP tool error:"):
                    raise RuntimeError(str(response)[:200])
                return {"id": key[1], "status": "cancel_requested"}
            except Exception as error:
                return {"id": key[1], "status": "cleanup_failed", "error": str(error)[:200]}

        results = await asyncio.gather(*(cancel(key, job) for key, job in self.jobs.items()))
        self.jobs.clear()
        return results
