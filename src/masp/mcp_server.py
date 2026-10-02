"""Built-in MASP Workspace MCP Server (supports both in-process and stdio execution)."""

import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from masp.chat_tools import list_workspace_files, run_chat_tool
from masp.workspace import GitError, git

BUILTIN_MCP_SERVER_ID = "builtin-masp-workspace"

server = MCPServer("Micro-Multi Workspace")


def _active_cwd(override: Path | None = None) -> Path:
    if override is not None:
        return override.resolve()
    env_cwd = os.environ.get("MASP_WORKSPACE_ROOT")
    if env_cwd:
        return Path(env_cwd).resolve()
    return Path.cwd().resolve()


def builtin_mcp_server_record(enabled: bool = True) -> dict[str, Any]:
    return {
        "id": BUILTIN_MCP_SERVER_ID,
        "name": "Micro-Multi Workspace MCP",
        "transport": "builtin",
        "command": sys.executable,
        "args": ["-m", "masp.mcp_server"],
        "url": "",
        "enabled": enabled,
        "builtin": True,
        "description": "提供工作区状态、Git 差异、文件读写、代码检索、命令执行与联网搜索服务。",
    }


def builtin_mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "workspace_info",
            "description": "获取当前工作区路径、Git 分支、改动文件数及最近一次提交信息。",
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "read_only": True,
        },
        {
            "name": "git_status",
            "description": "获取当前工作区的 Git 变更状态。",
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "read_only": True,
        },
        {
            "name": "git_diff",
            "description": "获取当前工作区或指定相对路径的 Git Diff。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "工作区内相对文件路径",
                    }
                },
                "additionalProperties": False,
            },
            "read_only": True,
        },
        {
            "name": "list_workspace_files",
            "description": "列出当前工作区或子目录下的文件与文件夹。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "subdirectory": {
                        "type": "string",
                        "description": "子目录相对路径",
                    }
                },
                "additionalProperties": False,
            },
            "read_only": True,
        },
        {
            "name": "read_workspace_file",
            "description": "读取工作区中指定 UTF-8 文本文件的内容。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "工作区内相对文件路径",
                    },
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            "read_only": True,
        },
        {
            "name": "search_workspace_code",
            "description": "在工作区源码中搜索关键字或正则并返回匹配文件路径与行号。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "subdirectory": {"type": "string"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            "read_only": True,
        },
        {
            "name": "glob_workspace_files",
            "description": "按通配符查找工作区内的文件路径。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "minLength": 1},
                    "subdirectory": {"type": "string"},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            "read_only": True,
        },
        {
            "name": "write_workspace_file",
            "description": "在工作区内创建或覆写 UTF-8 文本文件。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            "read_only": False,
        },
        {
            "name": "edit_workspace_file",
            "description": "精确替换工作区文件中的指定文本片段。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string", "minLength": 1},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
            "read_only": False,
        },
        {
            "name": "run_workspace_command",
            "description": "在工作区目录运行开发、测试或构建命令。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            "read_only": False,
        },
        {
            "name": "web_search",
            "description": "联网搜索实时网页与技术资料。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            "read_only": True,
        },
        {
            "name": "web_fetch",
            "description": "抓取指定 URL 网页内容并提取正文。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "minLength": 4},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 30000},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            "read_only": True,
        },
    ]


def execute_builtin_mcp_tool(
    name: str, parsed_args: dict[str, Any], cwd: Path | None = None
) -> str:
    root = _active_cwd(cwd)
    if name == "workspace_info":
        info: dict[str, Any] = {
            "workspace": str(root),
            "exists": root.is_dir(),
            "is_git_repo": False,
            "branch": "",
            "dirty_count": 0,
            "head_commit": "",
        }
        if root.is_dir():
            try:
                branch = git(root, "branch", "--show-current")
                status_text = git(root, "status", "--short")
                head = git(root, "log", "-1", "--pretty=%h %s")
                info.update(
                    {
                        "is_git_repo": True,
                        "branch": branch or "main",
                        "dirty_count": len(
                            [line for line in status_text.splitlines() if line.strip()]
                        ),
                        "head_commit": head,
                    }
                )
            except GitError:
                pass
        return json.dumps(info, ensure_ascii=False)
    if name == "git_status":
        try:
            return json.dumps(
                {"status": git(root, "status", "--short")},
                ensure_ascii=False,
            )
        except GitError as error:
            return json.dumps({"error": str(error)}, ensure_ascii=False)
    if name == "git_diff":
        rel = str(parsed_args.get("path", "")).strip()
        try:
            diff = git(root, "diff", "HEAD", "--", rel) if rel else git(root, "diff", "HEAD", "--")
            return diff[:12000] if diff else "No uncommitted diff."
        except GitError as error:
            return json.dumps({"error": str(error)}, ensure_ascii=False)
    if name == "list_workspace_files":
        subdir = str(parsed_args.get("subdirectory", "")).strip()
        try:
            items = list_workspace_files(root, subdir)
            return json.dumps({"files": items}, ensure_ascii=False)
        except (OSError, ValueError) as error:
            return json.dumps({"error": str(error)}, ensure_ascii=False)
    if name == "read_workspace_file":
        return run_chat_tool(root, "read_file", json.dumps(parsed_args))
    if name == "search_workspace_code":
        query = str(parsed_args.get("query", "")).strip()
        subdir = str(parsed_args.get("subdirectory", "")).strip()
        return run_chat_tool(
            root,
            "search_files",
            json.dumps({"query": query, "subdirectory": subdir}),
        )
    if name == "glob_workspace_files":
        return run_chat_tool(root, "glob", json.dumps(parsed_args))
    if name == "write_workspace_file":
        return run_chat_tool(root, "write_file", json.dumps(parsed_args))
    if name == "edit_workspace_file":
        return run_chat_tool(root, "edit_file", json.dumps(parsed_args))
    if name == "run_workspace_command":
        return run_chat_tool(root, "run_command", json.dumps(parsed_args))
    if name == "web_search":
        return run_chat_tool(root, "web_search", json.dumps(parsed_args))
    if name == "web_fetch":
        return run_chat_tool(root, "web_fetch", json.dumps(parsed_args))
    raise ValueError(f"Unknown built-in MCP tool: {name}")


@server.tool()
def workspace_info() -> str:
    """获取当前工作区路径、Git 分支、改动文件数及最近一次提交信息。"""
    return execute_builtin_mcp_tool("workspace_info", {})


@server.tool()
def git_status() -> str:
    """获取当前工作区的 Git 变更状态。"""
    return execute_builtin_mcp_tool("git_status", {})


@server.tool()
def git_diff(path: str = "") -> str:
    """获取当前工作区或指定相对路径的 Git Diff。"""
    return execute_builtin_mcp_tool("git_diff", {"path": path})


@server.tool()
def list_workspace_files_tool(subdirectory: str = "") -> str:
    """列出当前工作区或子目录下的文件与文件夹。"""
    return execute_builtin_mcp_tool("list_workspace_files", {"subdirectory": subdirectory})


@server.tool()
def read_workspace_file(
    path: str, start_line: int | None = None, end_line: int | None = None
) -> str:
    """读取工作区中指定 UTF-8 文本文件的内容。"""
    payload: dict[str, Any] = {"path": path}
    if start_line is not None:
        payload["start_line"] = start_line
    if end_line is not None:
        payload["end_line"] = end_line
    return execute_builtin_mcp_tool("read_workspace_file", payload)


@server.tool()
def search_workspace_code(query: str, subdirectory: str = "") -> str:
    """在工作区源码中搜索关键字并返回匹配文件路径与行号。"""
    return execute_builtin_mcp_tool(
        "search_workspace_code", {"query": query, "subdirectory": subdirectory}
    )


@server.tool()
def glob_workspace_files(pattern: str, subdirectory: str = "") -> str:
    """按通配符查找工作区内的文件路径。"""
    return execute_builtin_mcp_tool(
        "glob_workspace_files", {"pattern": pattern, "subdirectory": subdirectory}
    )


@server.tool()
def write_workspace_file(path: str, content: str) -> str:
    """在工作区内创建或覆写 UTF-8 文本文件。"""
    return execute_builtin_mcp_tool("write_workspace_file", {"path": path, "content": content})


@server.tool()
def edit_workspace_file(path: str, old_text: str, new_text: str) -> str:
    """精确替换工作区文件中的指定文本片段。"""
    return execute_builtin_mcp_tool(
        "edit_workspace_file", {"path": path, "old_text": old_text, "new_text": new_text}
    )


@server.tool()
def run_workspace_command(command: str) -> str:
    """在工作区目录运行开发、测试或构建命令。"""
    return execute_builtin_mcp_tool("run_workspace_command", {"command": command})


@server.tool()
def web_search(query: str, max_results: int = 6) -> str:
    """联网搜索实时网页与技术资料。"""
    return execute_builtin_mcp_tool("web_search", {"query": query, "max_results": max_results})


@server.tool()
def web_fetch(url: str, max_chars: int = 12000) -> str:
    """抓取指定 URL 网页内容并提取正文。"""
    return execute_builtin_mcp_tool("web_fetch", {"url": url, "max_chars": max_chars})


if __name__ == "__main__":
    server.run(transport="stdio")
