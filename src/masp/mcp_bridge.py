"""MCP stdio/HTTP/built-in server discovery and tool calls for the coordinating agent."""

import asyncio
import json
import os
import re
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from masp.mcp_connections import connection
from masp.mcp_server import (
    BUILTIN_MCP_SERVER_ID,
    builtin_mcp_server_record,
    builtin_mcp_tools,
    execute_builtin_mcp_tool,
)
from masp.storage import Store, now

_discovery_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _discovery_key(server: dict[str, Any], cwd: Path) -> str:
    operational = {
        key: value
        for key, value in server.items()
        if key not in {"connection_status", "last_error", "last_probe_at", "updated_at"}
    }
    return str(cwd.resolve()) + json.dumps(operational, sort_keys=True)


def _resolve_command(command: str) -> str:
    if not command:
        return command
    path = Path(command)
    if path.is_absolute() or len(path.parts) > 1:
        return command
    if os.name == "nt" and command.lower() in {"npx", "npm", "pnpm", "yarn", "uvx", "node"}:
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return command


def _parameters(server: dict[str, Any], cwd: Path) -> StdioServerParameters | str:
    if server.get("transport", "stdio") == "http":
        return str(server["url"])
    command = str(server.get("command", "")).strip()
    configured_cwd = (cwd / Path(server["cwd"])) if server.get("cwd") else cwd
    raw_env = server.get("env")
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "LANG",
            "APPDATA",
            "LOCALAPPDATA",
            "COMSPEC",
            "PATHEXT",
            "PROGRAMFILES",
        }
    }
    if isinstance(raw_env, dict):
        env.update({str(key): str(value) for key, value in raw_env.items()})
    args = [str(arg) for arg in server.get("args", [])]
    # Fail before spawning with a dependency error the agent can act on.
    # Resolve using this server's PATH, including Windows npm-generated shims.
    resolved = shutil.which(command, path=env.get("PATH"))
    if not resolved:
        candidate = Path(command)
        if not candidate.is_absolute():
            candidate = configured_cwd / candidate
        if candidate.is_file():
            resolved = str(candidate.resolve())
        else:
            raise FileNotFoundError(
                f"MCP executable not found: {command}. Install the provider CLI or configure "
                "an absolute command path; registering a plugin does not install its dependencies."
            )
    # npm's Windows shims use cmd parsing. Launch the actual Node CLI instead,
    # preserving spaces and metacharacters as literal argv, and never prompting.
    if Path(resolved).suffix.lower() in {".cmd", ".bat"} and Path(resolved).stem.lower() in {
        "npx",
        "npm",
    }:
        node = shutil.which("node", path=env.get("PATH"))
        cli = (
            Path(resolved).parent
            / "node_modules"
            / "npm"
            / "bin"
            / ("npx-cli.js" if Path(resolved).stem.lower() == "npx" else "npm-cli.js")
        )
        if node and cli.is_file():
            args.insert(0, str(cli))
            resolved = node
    if command.lower() in {"npx", "npx.cmd"} or Path(command).stem.lower() == "npx":
        if not any(arg in {"-y", "--yes", "--no"} for arg in args):
            args.insert(1 if args and args[0].endswith("npx-cli.js") else 0, "--yes")
    return StdioServerParameters(
        command=resolved,
        args=args,
        cwd=configured_cwd,
        env=env,
    )


@asynccontextmanager
async def _open_transport(
    server: dict[str, Any], cwd: Path, read_timeout: float
) -> AsyncIterator[Any]:
    if server.get("transport") == "http" and server.get("headers"):
        async with httpx2.AsyncClient(
            headers=server["headers"], timeout=read_timeout
        ) as http_client:
            transport = streamable_http_client(str(server["url"]), http_client=http_client)
            async with Client(transport, read_timeout_seconds=read_timeout) as client:
                yield client
    else:
        async with Client(_parameters(server, cwd), read_timeout_seconds=read_timeout) as client:
            yield client


@asynccontextmanager
async def _open_client(
    server: dict[str, Any], cwd: Path, read_timeout: float
) -> AsyncIterator[Any]:
    actor = connection(
        server, cwd, lambda: _open_transport(server, cwd, float(server.get("timeout_seconds", 180)))
    )
    yield actor


def discover_project_mcp_servers(cwd: Path) -> list[dict[str, Any]]:
    """Discover MCP servers declared in .mcp.json or mcp.json inside a project."""
    servers: list[dict[str, Any]] = []
    if not cwd or not cwd.is_dir():
        return servers
    for filename in (".mcp.json", "mcp.json"):
        candidate = cwd / filename
        if (
            not candidate.is_file()
            or candidate.stat().st_size > 1_000_000
            or candidate.is_symlink()
        ):
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        mcp_map = data.get("mcpServers") or data.get("servers") or data
        if not isinstance(mcp_map, dict):
            continue
        for key, spec in mcp_map.items():
            if not isinstance(spec, dict):
                continue
            server_id = "proj-mcp-" + re.sub(r"[^a-zA-Z0-9_-]", "-", str(key))[:48]
            url = str(spec.get("url") or spec.get("httpUrl") or "").strip()
            transport = "http" if url else str(spec.get("transport", "stdio"))
            command = str(spec.get("command", "")).strip()
            if transport == "stdio" and not command:
                continue
            servers.append(
                {
                    "id": server_id,
                    "name": str(spec.get("name") or key),
                    "transport": transport,
                    "command": command,
                    "args": [str(item) for item in spec.get("args", [])]
                    if isinstance(spec.get("args"), list)
                    else [],
                    "url": url,
                    "env": spec.get("env") if isinstance(spec.get("env"), dict) else {},
                    "headers": spec.get("headers") if isinstance(spec.get("headers"), dict) else {},
                    "cwd": str(cwd / str(spec.get("cwd") or ".")),
                    "enabled": bool(spec.get("enabled", True)),
                    "source": str(candidate),
                }
            )
    return servers


async def probe_server(server: dict[str, Any], cwd: Path) -> list[dict[str, Any]]:
    if server.get("transport") == "builtin" or server.get("id") == BUILTIN_MCP_SERVER_ID:
        return [
            {
                "name": item["name"],
                "description": item["description"],
                "input_schema": item["input_schema"],
            }
            for item in builtin_mcp_tools()
        ]

    async def connect() -> list[dict[str, Any]]:
        async with _open_client(server, cwd, 20) as client:
            tools = await client.list_tools()
            all_tools = list(tools.tools)
            seen_cursors: set[str] = set()
            cursor = getattr(tools, "next_cursor", None)
            while cursor and len(all_tools) < 1000:
                if cursor in seen_cursors:
                    raise ValueError("MCP pagination repeated its cursor")
                seen_cursors.add(cursor)
                page = await client.list_tools(cursor=cursor)
                all_tools.extend(page.tools)
                cursor = getattr(page, "next_cursor", None)
            result: list[dict[str, Any]] = []
            for item in all_tools[:1000]:
                schema = getattr(item, "input_schema", None)
                if schema is None:
                    schema = getattr(item, "inputSchema", None)
                if not isinstance(schema, dict):
                    schema = {"type": "object", "properties": {}}
                result.append(
                    {
                        "name": item.name,
                        "description": item.description or "",
                        "input_schema": schema,
                    }
                )
            return result

    return await asyncio.wait_for(
        connect(), timeout=float(server.get("startup_timeout_seconds", 120))
    )


def _is_builtin_mcp_enabled(store: Store) -> bool:
    try:
        settings = store.get("dsh_setting", "global")
        inventory = settings.get("pluginInventory", {})
        if isinstance(inventory, dict) and inventory.get("@masp/workspace-mcp") is False:
            return False
    except KeyError:
        pass
    return True


async def discover_tools(
    store: Store,
    cwd: Path,
    *,
    include_builtin: bool = False,
    access_mode: str = "commands",
) -> tuple[list[dict[str, Any]], dict[str, tuple[dict[str, Any], str]]]:
    schemas: list[dict[str, Any]] = []
    lookup: dict[str, tuple[dict[str, Any], str]] = {}
    servers: list[dict[str, Any]] = []
    if include_builtin and _is_builtin_mcp_enabled(store):
        servers.append(builtin_mcp_server_record(enabled=True))
    stored_servers = store.list("mcp_server")
    stored_ids = {item["id"] for item in stored_servers}
    servers.extend(stored_servers)
    existing_names = {item.get("name", "").casefold() for item in servers}
    for proj_server in discover_project_mcp_servers(cwd):
        if proj_server["name"].casefold() not in existing_names:
            servers.append(proj_server)
            existing_names.add(proj_server["name"].casefold())

    capacity = asyncio.Semaphore(4)

    async def probe(server: dict[str, Any]) -> list[dict[str, Any]]:
        async with capacity:
            cache_key = _discovery_key(server, cwd)
            cached = _discovery_cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < 30:
                return deepcopy(cached[1])
            try:
                result = await probe_server(server, cwd)
            except Exception as error:
                if server.get("id") in stored_ids:
                    await asyncio.to_thread(
                        store.update,
                        "mcp_server",
                        server["id"],
                        connection_status="failed",
                        last_error=f"{type(error).__name__}: {str(error)[:300]}",
                        last_probe_at=now(),
                    )
                return []
            if len(_discovery_cache) >= 128:
                oldest = min(_discovery_cache, key=lambda key: _discovery_cache[key][0])
                _discovery_cache.pop(oldest, None)
            _discovery_cache[cache_key] = (time.monotonic(), deepcopy(result))
            if server.get("id") in stored_ids:
                await asyncio.to_thread(
                    store.update,
                    "mcp_server",
                    server["id"],
                    connection_status="connected",
                    last_error=None,
                    last_probe_at=now(),
                )
            return result

    disabled_bundles = {item["id"] for item in store.list("dsh_bundle") if not item.get("enabled")}
    active = [
        server
        for server in servers
        if server.get("enabled")
        and server.get("bundle_id") not in disabled_bundles
        and (access_mode != "read" or server.get("id") == BUILTIN_MCP_SERVER_ID)
    ]
    results = await asyncio.gather(*(probe(server) for server in active))
    for server, found in zip(active, results, strict=True):
        for index, item in enumerate(found):
            raw_id = re.sub(r"[^a-zA-Z0-9_]", "_", str(server["id"]))
            tool_slug = re.sub(r"[^a-zA-Z0-9_]", "_", str(item["name"]))[:28]
            alias = (
                f"mcp_builtin_{tool_slug}"
                if server.get("id") == BUILTIN_MCP_SERVER_ID
                else f"mcp_{raw_id}_{index}"
            )
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": alias,
                        "description": (f"MCP {server['name']}: {item['description']}")[:1000],
                        "parameters": item["input_schema"],
                    },
                }
            )
            lookup[alias] = (server, item["name"])
    return schemas, lookup


async def call_tool(server: dict[str, Any], name: str, arguments: str, cwd: Path) -> str:
    parsed = json.loads(arguments) if arguments.strip() else {}
    if not isinstance(parsed, dict):
        raise ValueError("MCP tool arguments must be an object")

    if server.get("transport") == "builtin" or server.get("id") == BUILTIN_MCP_SERVER_ID:
        return await asyncio.to_thread(execute_builtin_mcp_tool, name, parsed, cwd)

    async def invoke() -> str:
        async with _open_client(server, cwd, 30) as client:
            result = await client.call_tool(name, parsed)
            text = "\n".join(item.text for item in result.content if isinstance(item, TextContent))
            if result.is_error:
                return "MCP tool error: " + text[:12000]
            if result.structured_content is not None:
                return json.dumps(result.structured_content, ensure_ascii=False)[:12000]
            return text[:12000]

    return await asyncio.wait_for(invoke(), timeout=float(server.get("timeout_seconds", 180)))
