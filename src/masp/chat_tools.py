"""Project-scoped tools available to the coordinating chat agent."""

import difflib
import fnmatch
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

from masp.domain import safe_path
from masp.memory_os import MemoryOS
from masp.skills import list_skills, load_skill, read_skill_resource

MAX_FILE_BYTES = 2_048_000
MAX_RESULTS = 200

CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "精确替换文件中的一处文本；旧文本必须存在且唯一，返回新增与删除行数及差异。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string", "minLength": 1},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "创建或替换 UTF-8 文件；append=true 时追加。每次内容建议不超过 2000 字符，大文件必须分段写入，避免输出截断。返回差异。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "append": {"type": "boolean"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "删除当前工作区内的指定文件或目录，返回删除结果与清理行数。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取工作区中的 UTF-8 文本文件，可选指定起始行与结束行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出工作区内的普通源文件路径。",
            "parameters": {
                "type": "object",
                "properties": {"subdirectory": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "按通配符模式查找工作区内的文件路径，如 *.py 或 src/**/*.ts。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "minLength": 1},
                    "subdirectory": {"type": "string"},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "使用正则表达式或关键字在工作区文件中搜索匹配行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "minLength": 1},
                    "subdirectory": {"type": "string"},
                    "include": {"type": "string"},
                    "case_insensitive": {"type": "boolean"},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "在工作区文本文件中查找文字，返回路径和行号。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "subdirectory": {"type": "string"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "在当前工作区目录运行开发、测试、构建、脚本或版本控制命令。"
                + (
                    "当前系统是 Windows，完全访问模式使用 cmd.exe；不支持 Bash heredoc。"
                    "复杂 Python/Node 代码先 write_file 写入脚本再执行，避免内联引号和管道解析错误。"
                    "需要 PowerShell 时显式调用 powershell -NoProfile -Command。"
                    if os.name == "nt"
                    else "当前系统使用 POSIX shell。"
                )
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索实时资讯、技术文档或开源仓库信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "访问指定网页 URL 并提取正文文本内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "minLength": 4},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 30000},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_store",
            "description": "向 Memory OS 长期记忆系统写入重要事实、项目架构决策、用户偏好或核心指令。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "minLength": 1},
                    "category": {
                        "type": "string",
                        "enum": ["preference", "architecture", "fact", "rule", "skill_hint"],
                    },
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "core_block": {
                        "type": "string",
                        "enum": ["user_preferences", "project_architecture", "active_directives"],
                    },
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "在 Memory OS 中检索核心记忆、语义事实记忆、历史执行轨迹与文件关系图谱。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_update",
            "description": "更新 Memory OS 中已有的记忆条目或核心记忆块。",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "content": {"type": "string", "minLength": 1},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["memory_id", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_delete",
            "description": "从 Memory OS 中删除过时或错误的记忆条目。",
            "parameters": {
                "type": "object",
                "properties": {"target": {"type": "string", "minLength": 1}},
                "required": ["target"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "core_memory_append",
            "description": "向 Letta 分层记忆系统的 Core Memory 块追加关键事实或工作状态（支持 persona, human, project_architecture, working_context 等块）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "enum": [
                            "persona",
                            "human",
                            "project_architecture",
                            "working_context",
                            "user_preferences",
                            "active_directives",
                        ],
                    },
                    "content": {"type": "string", "minLength": 1},
                },
                "required": ["label", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "core_memory_replace",
            "description": "替换 Letta 分层记忆系统 Core Memory 块中的特定内容或重写整个块。",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "enum": [
                            "persona",
                            "human",
                            "project_architecture",
                            "working_context",
                            "user_preferences",
                            "active_directives",
                        ],
                    },
                    "old_content": {"type": "string"},
                    "new_content": {"type": "string"},
                },
                "required": ["label", "new_content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "archival_memory_insert",
            "description": "向 Letta 归档记忆（Archival Memory）中持久化存入长文本规范、技术文档、项目历史或背景知识。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "minLength": 1},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "archival_memory_search",
            "description": "在 Letta 归档记忆（Archival Memory）中检索语义相关的长文本档案和知识。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory_search",
            "description": "在 Letta 回忆记忆（Recall Memory）中检索过往对话轨迹、历史执行轮次与事件记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "列出项目或用户配置的可复用 Agent 技能及描述。",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "按技能名加载 SKILL.md 的完整指令内容。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_plugin",
            "description": "按用户要求在对话中加载、安装或启用插件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "插件名称、ID 或本地目录路径"},
                    "path": {"type": "string", "description": "本地插件目录或清单文件路径"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plugin_manager",
            "description": "管理本地 JSON 工具、MCP、Skill 和原生 Cordis Host 插件。支持启停、安装、移除；不支持 Client 界面插件或 npm 安装。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "install",
                            "enable",
                            "disable",
                            "reload",
                            "remove",
                            "list_plugins",
                            "list_bundles",
                            "install_bundle",
                            "set_plugin",
                            "set_bundle",
                            "remove_bundle",
                        ],
                    },
                    "target": {
                        "type": "string",
                        "description": "插件名称、ID 或本地路径",
                    },
                    "enabled": {"type": "boolean"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_team",
            "description": "用户明确要求开始多智能体协同开发或修改上一轮成果时启动团队运行。",
            "parameters": {
                "type": "object",
                "properties": {"requirement": {"type": "string"}},
                "required": ["requirement"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "configure_team",
            "description": "按用户指令创建或调整当前项目的子 Agent 团队配置。",
            "parameters": {
                "type": "object",
                "properties": {"instruction": {"type": "string"}},
                "required": ["instruction"],
                "additionalProperties": False,
            },
        },
    },
]

CHAT_TOOLS.append(
    {
        "type": "function",
        "function": {
            "name": "read_skill_resource",
            "description": "读取已加载技能目录内的 scripts、references 或 assets 文本资源。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "path": {"type": "string"}},
                "required": ["name", "path"],
                "additionalProperties": False,
            },
        },
    }
)


def _safe_file(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ValueError("需要项目内的相对路径")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()):
        raise ValueError("路径超出项目目录")
    if not path.is_file():
        raise ValueError("目标不是普通文件")
    parts = {part.casefold() for part in path.relative_to(root.resolve()).parts}
    name = path.name.casefold()
    relative_parts = path.relative_to(root.resolve()).parts
    plan_document = (
        len(relative_parts) == 4
        and relative_parts[:2] == (".masp", "team-plans")
        and name in {"requirements.md", "design.md", "tasks.md"}
    )
    if ".git" in parts or (".masp" in parts and not plan_document) or name.startswith(".env"):
        raise ValueError("此类文件不能通过聊天工具读取")
    if name.endswith((".pem", ".key", ".p12", ".pfx")) or "secret" in name:
        raise ValueError("此类文件不能通过聊天工具读取")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("文件超过 128 KB 读取上限")
    return path


def _files(root: Path, subdirectory: str = "") -> list[Path]:
    base = root.resolve()
    folder = (base / subdirectory).resolve(strict=True) if subdirectory else base
    if not folder.is_relative_to(base) or not folder.is_dir():
        raise ValueError("目录必须位于项目内")
    items = []
    hidden_dirs = {".git", ".masp", "node_modules", ".venv", "venv", "__pycache__"}
    for path in folder.rglob("*"):
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(base) or not resolved.is_file():
                continue
            relative = resolved.relative_to(base)
            parts = {part.casefold() for part in relative.parts}
            name = resolved.name.casefold()
            if parts.intersection(hidden_dirs) or name.startswith(".env"):
                continue
            if name.endswith((".pem", ".key", ".p12", ".pfx")) or "secret" in name:
                continue
            items.append(resolved)
            if len(items) >= MAX_RESULTS:
                break
        except OSError:
            continue
    return items


def _strip_html_to_text(raw_html: str) -> tuple[str, str]:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.I | re.S)
    title = html.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else ""
    cleaned = re.sub(
        r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw_html, flags=re.I | re.S
    )
    cleaned = re.sub(
        r"</(p|div|li|tr|h[1-6]|section|article|header|footer|br)\s*>", "\n", cleaned, flags=re.I
    )
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()]
    text = "\n".join(line for line in lines if line)
    return title, text


def execute_web_fetch(url: str, max_chars: int = 12000) -> str:
    target = url.strip()
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8",
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=12.0, headers=headers) as client:
            resp = client.get(target)
            content_type = resp.headers.get("content-type", "").lower()
            if "json" in content_type or "text/plain" in content_type or "markdown" in content_type:
                return json.dumps(
                    {
                        "url": str(resp.url),
                        "status": resp.status_code,
                        "title": str(resp.url),
                        "content": resp.text[:max_chars],
                    },
                    ensure_ascii=False,
                )
            title, text = _strip_html_to_text(resp.text)
            return json.dumps(
                {
                    "url": str(resp.url),
                    "status": resp.status_code,
                    "title": title or str(resp.url),
                    "content": text[:max_chars],
                },
                ensure_ascii=False,
            )
    except httpx.HTTPError as error:
        return json.dumps({"url": target, "error": f"访问网页失败：{error}"}, ensure_ascii=False)


def execute_web_search(query: str, max_results: int = 6) -> str:
    q = query.strip()
    if not q:
        return json.dumps({"query": "", "results": []}, ensure_ascii=False)
    limit = max(1, min(10, int(max_results or 6)))
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    results: list[dict[str, str]] = []
    rss_urls = [
        f"https://cn.bing.com/search?q={urllib.parse.quote(q)}&format=rss",
        f"https://www.bing.com/search?q={urllib.parse.quote(q)}&format=rss",
    ]
    for rss_url in rss_urls:
        try:
            with httpx.Client(follow_redirects=True, timeout=10.0, headers=headers) as client:
                resp = client.get(rss_url)
                if resp.status_code == 200 and "<item>" in resp.text:
                    for item in re.findall(r"<item>(.*?)</item>", resp.text, flags=re.S):
                        t_m = re.search(r"<title>(.*?)</title>", item, flags=re.S)
                        l_m = re.search(r"<link>(.*?)</link>", item, flags=re.S)
                        d_m = re.search(r"<description>(.*?)</description>", item, flags=re.S)
                        if l_m:
                            results.append(
                                {
                                    "title": html.unescape(
                                        re.sub(r"<[^>]+>", "", t_m.group(1) if t_m else "")
                                    ).strip(),
                                    "url": html.unescape(l_m.group(1)).strip(),
                                    "snippet": html.unescape(
                                        re.sub(r"<[^>]+>", "", d_m.group(1) if d_m else "")
                                    ).strip(),
                                }
                            )
                            if len(results) >= limit:
                                break
                if results:
                    break
        except httpx.HTTPError:
            continue

    if not results:
        try:
            ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}"
            with httpx.Client(follow_redirects=True, timeout=10.0, headers=headers) as client:
                resp = client.get(ddg_url)
                for match in re.finditer(
                    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                    resp.text,
                    flags=re.I | re.S,
                ):
                    href = html.unescape(match.group(1))
                    if "uddg=" in href:
                        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                        href = parsed_qs.get("uddg", [href])[0]
                    title = html.unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
                    results.append({"title": title, "url": href, "snippet": ""})
                    if len(results) >= limit:
                        break
        except httpx.HTTPError as error:
            return json.dumps(
                {"query": q, "results": [], "error": f"联网搜索请求失败：{error}"},
                ensure_ascii=False,
            )

    return json.dumps({"query": q, "results": results}, ensure_ascii=False)


def run_chat_tool(
    root: Path | str | None = None,
    name: str = "",
    arguments: str = "{}",
    skills_home: Path | None = None,
    command_timeout_seconds: int = 120,
    allowed_paths: list[str] | None = None,
    *,
    cwd: Path | None = None,
    timeout_seconds: int | None = None,
    enabled_plugins: list[Any] | None = None,
    block_destructive_git: bool = True,
    access_mode: str = "workspace",
    cancel_signal: Any = None,
) -> str:
    from functools import partial

    from masp.managed_commands import command_run

    command_runner = (
        partial(command_run, cancel_signal=cancel_signal)
        if cancel_signal is not None
        else subprocess.run
    )
    try:
        if timeout_seconds is not None:
            command_timeout_seconds = int(timeout_seconds)
        if cwd is not None and isinstance(root, str) and not Path(root).is_absolute():
            # Called as run_chat_tool(name, arguments, cwd=...)
            arguments = name if name and name != "{}" else arguments
            name = root
            effective_root: Path | str | None = cwd
        else:
            effective_root = root if root is not None else cwd
        if effective_root is None:
            raise ValueError("缺少工作区根目录")
        root = Path(effective_root)
        raw_args = (arguments or "").strip()
        parsed: Any = {}
        if raw_args:
            try:
                parsed = json.loads(raw_args)
            except Exception:
                if name == "write_file":
                    m_path = re.search(r'"path"\s*:\s*"([^"]+)"', raw_args)
                    m_content = re.search(r'"content"\s*:\s*"([\s\S]*)', raw_args)
                    if m_content:
                        raw_c = m_content.group(1)
                        raw_c = re.sub(r'"\s*(?:,\s*"path"\s*:\s*"[^"]*"\s*)?\}\s*$', "", raw_c)
                        rec_content = (
                            raw_c.replace("\\n", "\n")
                            .replace("\\r", "\r")
                            .replace("\\t", "\t")
                            .replace('\\"', '"')
                            .replace("\\\\", "\\")
                        )
                        if m_path:
                            rec_path = m_path.group(1).strip()
                        elif allowed_paths and any("." in Path(p).name for p in allowed_paths):
                            rec_path = next(p for p in allowed_paths if "." in Path(p).name)
                        elif "<svg" in rec_content.lower():
                            rec_path = "pelican_bicycle.svg"
                        elif (
                            "<html" in rec_content.lower()
                            or "<!doctype html" in rec_content.lower()
                        ):
                            rec_path = "index.html"
                        else:
                            raise
                        if (
                            rec_path.lower().endswith(".svg")
                            and "<svg" in rec_content.lower()
                            and "</svg>" not in rec_content.lower()
                        ):
                            rec_content += "\n</svg>\n"
                        elif (
                            rec_path.lower().endswith((".html", ".htm"))
                            and "<html" in rec_content.lower()
                            and "</html>" not in rec_content.lower()
                        ):
                            rec_content += "\n</body>\n</html>\n"
                        parsed = {"path": rec_path, "content": rec_content}
                    else:
                        raise
                else:
                    raise
        if not isinstance(parsed, dict):
            return "工具参数必须是 JSON 对象。"
        args: dict[str, Any] = parsed
        if access_mode == "read" and name in {
            "write_file",
            "edit_file",
            "delete_file",
            "run_command",
        }:
            return f"当前安全权限为只读模式，已拦截工具：{name}"
        if name in {"write_file", "edit_file", "delete_file"}:
            relative = safe_path(args["path"])
            if allowed_paths is not None and not any(
                scope in {".", "*", "**", "./"}
                or relative == scope
                or relative.startswith(scope.rstrip("/") + "/")
                for scope in allowed_paths
            ):
                raise ValueError("文件不在当前 Agent 的任务范围内")
        if name == "delete_file":
            relative = safe_path(args["path"])
            if relative.casefold() in {".git", ".masp"} or relative.casefold().startswith(
                (".git/", ".masp/")
            ):
                raise ValueError("不能删除 .git 或 .masp 目录")
            candidate_target = (root.resolve() / relative).resolve()
            if (
                not candidate_target.is_relative_to(root.resolve())
                or candidate_target == root.resolve()
            ):
                raise ValueError("路径超出项目目录")
            if candidate_target.is_dir():
                shutil.rmtree(candidate_target)
                return json.dumps(
                    {
                        "deleted": relative,
                        "written": relative,
                        "added": 0,
                        "removed": 1,
                        "diff": f"--- a/{relative}/\n+++ /dev/null\n-Directory {relative}/ removed",
                    },
                    ensure_ascii=False,
                )
            target_file = _safe_file(root.resolve(), relative)
            try:
                old_lines = target_file.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                old_lines = []
            target_file.unlink()
            return json.dumps(
                {
                    "deleted": relative,
                    "written": relative,
                    "added": 0,
                    "removed": len(old_lines),
                    "diff": f"--- a/{relative}\n+++ /dev/null\n"
                    + "\n".join(f"-{ln}" for ln in old_lines[:120]),
                },
                ensure_ascii=False,
            )
        if name == "edit_file":
            path = _safe_file(root.resolve(), args["path"])
            content = path.read_text(encoding="utf-8")
            old_text, new_text = args["old_text"], args["new_text"]
            if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
                raise ValueError("替换参数必须是文本，旧文本不能为空")
            if (
                old_text not in content
                and "\r\n" in content
                and old_text in content.replace("\r\n", "\n")
            ):
                content = content.replace("\r\n", "\n")
            if content.count(old_text) != 1:
                raise ValueError("旧文本必须在文件中恰好出现一次，请重新读取文件并提供更多上下文")
            return run_chat_tool(
                root,
                "write_file",
                json.dumps(
                    {"path": args["path"], "content": content.replace(old_text, new_text, 1)}
                ),
                skills_home,
                command_timeout_seconds,
                allowed_paths,
                block_destructive_git=block_destructive_git,
                access_mode=access_mode,
            )
        if name == "list_skills":
            return json.dumps({"skills": list_skills(root, skills_home)}, ensure_ascii=False)
        if name == "load_skill":
            return load_skill(root, skills_home, args["name"])
        if name == "read_skill_resource":
            return read_skill_resource(root, skills_home, args["name"], args["path"])
        if name == "list_files":
            paths = _files(root, args.get("subdirectory", ""))
            return json.dumps(
                {"files": [path.relative_to(root.resolve()).as_posix() for path in paths]},
                ensure_ascii=False,
            )
        if name == "glob":
            pattern = str(args.get("pattern", "*")).strip() or "*"
            paths = _files(root, str(args.get("subdirectory", "")).strip())
            matched = []
            for path in paths:
                rel = path.relative_to(root.resolve()).as_posix()
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(path.name, pattern):
                    matched.append(rel)
            return json.dumps(
                {"pattern": pattern, "files": matched, "matches": matched}, ensure_ascii=False
            )
        if name == "read_file":
            path = _safe_file(root.resolve(), args["path"])
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return "读取失败：文件不是 UTF-8 文本。"
            start_line = args.get("start_line")
            end_line = args.get("end_line")
            if start_line is not None or end_line is not None:
                lines = text.splitlines()
                s_idx = max(1, int(start_line or 1))
                e_idx = min(len(lines), int(end_line or len(lines)))
                sliced = [f"{num}: {lines[num - 1]}" for num in range(s_idx, e_idx + 1)]
                return json.dumps(
                    {
                        "path": safe_path(args["path"]),
                        "start_line": s_idx,
                        "end_line": e_idx,
                        "content": "\n".join(sliced),
                    },
                    ensure_ascii=False,
                )
            return text
        if name == "write_file":
            relative = args["path"]
            if not isinstance(relative, str) or not isinstance(args["content"], str):
                raise ValueError("文件路径和内容必须是文本")
            if len(args["content"].encode("utf-8")) > MAX_FILE_BYTES:
                raise ValueError("文件超过 128 KB 写入上限")
            rel_path = Path(relative)
            if rel_path.is_absolute() or any(part in {"", ".", ".."} for part in rel_path.parts):
                raise ValueError("需要项目内的安全相对路径")
            destination = (root.resolve() / rel_path).resolve()
            if not destination.is_relative_to(root.resolve()):
                raise ValueError("路径超出项目目录")
            old_content = ""
            if destination.exists():
                destination = _safe_file(root.resolve(), relative)
                try:
                    old_content = destination.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    old_content = ""
            else:
                parts = {part.casefold() for part in rel_path.parts}
                if (
                    ".git" in parts
                    or ".masp" in parts
                    or destination.name.casefold().startswith(".env")
                    or "secret" in destination.name.casefold()
                ):
                    raise ValueError("此类文件不能通过聊天工具写入")
                if destination.name.casefold().endswith((".pem", ".key", ".p12", ".pfx")):
                    raise ValueError("此类文件不能通过聊天工具写入")
                destination.parent.mkdir(parents=True, exist_ok=True)
            new_content = (old_content if args.get("append") is True else "") + args["content"]
            if len(new_content.encode("utf-8")) > MAX_FILE_BYTES:
                raise ValueError("文件超过 128 KB 写入上限")
            diff_lines = list(
                difflib.unified_diff(
                    old_content.splitlines(),
                    new_content.splitlines(),
                    fromfile=f"a/{relative}",
                    tofile=f"b/{relative}",
                    lineterm="",
                )
            )
            added = sum(
                1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
            )
            removed = sum(
                1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
            )
            destination.write_text(new_content, encoding="utf-8", newline="\n")
            return json.dumps(
                {
                    "written": relative,
                    "bytes": len(new_content.encode("utf-8")),
                    "added": added,
                    "removed": removed,
                    "diff": "\n".join(diff_lines[:240]),
                },
                ensure_ascii=False,
            )
        if name == "run_command":
            command = args["command"]
            max_cmd_len = 8000 if access_mode == "commands" else 2000
            if not isinstance(command, str) or not command.strip() or len(command) > max_cmd_len:
                raise ValueError("命令长度无效")
            blocked_git = {"push", "clean", "reset", "-D", "--force"}
            if block_destructive_git and re.search(r"(?:^|[;&|]\s*)git\b", command.strip()):
                try:
                    git_tokens = shlex.split(command, posix=(os.name != "nt"))
                except ValueError:
                    git_tokens = command.split()
                if any(part in git_tokens for part in blocked_git):
                    return json.dumps(
                        {"blocked": True, "error": "此 Git 命令会删除或向远端写入数据，已禁止"},
                        ensure_ascii=False,
                    )
            py_dir = str(Path(sys.executable).resolve().parent)
            run_env = {
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "PATH": py_dir + os.pathsep + os.environ.get("PATH", ""),
            }
            if access_mode == "commands":
                # Full access mode (完全访问): unlock all shell commands, pipes, and scripts
                cmd_stripped = command.strip()
                # Make direct Python invocation independent of the Windows console code page.
                if os.name == "nt":
                    command = re.sub(
                        r"(?i)(^)python(?:3)?(?:\.exe)?(?=\s)", r"\1python -X utf8", command
                    )
                    cmd_stripped = command.strip()
                if os.name == "nt" and re.match(
                    r"^ls(?:\s+-[a-zA-Z]+)*(?:\s+([^\s|;&>]+))?\s*$", cmd_stripped
                ):
                    m_ls = re.match(r"^ls(?:\s+-[a-zA-Z]+)*(?:\s+([^\s|;&>]+))?\s*$", cmd_stripped)
                    target_dir = (m_ls.group(1) if m_ls and m_ls.group(1) else ".").strip("'\"")
                    py_code = (
                        "import os, pathlib; p = pathlib.Path("
                        + repr(target_dir)
                        + "); items = sorted(os.listdir(p)) if p.is_dir() else ([str(p)] if p.exists() else []); print('\\n'.join(items))"
                    )
                    result = command_runner(
                        [sys.executable, "-X", "utf8", "-c", py_code],
                        cwd=root.resolve(),
                        env=run_env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=30,
                        shell=False,
                    )
                elif os.name == "nt" and cmd_stripped == "pwd":
                    result = command_runner(
                        [sys.executable, "-X", "utf8", "-c", "import os; print(os.getcwd())"],
                        cwd=root.resolve(),
                        env=run_env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=30,
                        shell=False,
                    )
                else:
                    result = command_runner(
                        command,
                        cwd=root.resolve(),
                        env=run_env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=max(30, min(300, command_timeout_seconds)),
                        shell=True,
                    )
                return json.dumps(
                    {
                        "exit_code": result.returncode,
                        "stdout": result.stdout[-16000:],
                        "stderr": result.stderr[-16000:],
                    },
                    ensure_ascii=False,
                )
            if any(token in command for token in ("&&", "||", ";", "|", ">", "<", "`", "$(", "\n")):
                raise ValueError("一次只允许执行单条命令，不能使用 shell 管道或重定向")
            argv = shlex.split(command)
            if not argv:
                raise ValueError("命令不能为空")
            executable = Path(argv[0]).name.casefold()
            if executable.endswith(".exe"):
                executable = executable[:-4]
            allowed_commands = {
                "git",
                "python",
                "python3",
                "pytest",
                "ruff",
                "mypy",
                "node",
                "npm",
                "npx",
                "pnpm",
                "yarn",
                "bun",
                "cargo",
                "go",
                "dotnet",
                "pip",
                "uv",
                "poetry",
                "rg",
                "fd",
                "ls",
                "dir",
                "cat",
                "echo",
                "pwd",
                "whoami",
                "curl",
            }
            if executable not in allowed_commands:
                raise ValueError(
                    "允许的命令：git、python、pytest、ruff、mypy、node、npm、pnpm、yarn、bun、cargo、go、dotnet、pip、uv、rg"
                )
            if (
                block_destructive_git
                and executable == "git"
                and any(part in argv for part in blocked_git)
            ):
                return json.dumps(
                    {"blocked": True, "error": "此 Git 命令会删除或向远端写入数据，已禁止"},
                    ensure_ascii=False,
                )
            if executable in {"python", "python3"}:
                argv = [sys.executable, "-X", "utf8", *argv[1:]]
            elif os.name == "nt":
                resolved = shutil.which(argv[0])
                if resolved:
                    argv = [resolved, *argv[1:]]
                elif executable == "ls":
                    argv = [
                        sys.executable,
                        "-X",
                        "utf8",
                        "-c",
                        "import os; print('\\n'.join(sorted(os.listdir('.'))))",
                    ]
                elif executable == "pwd":
                    argv = [sys.executable, "-X", "utf8", "-c", "import os; print(os.getcwd())"]
            result = command_runner(
                argv,
                cwd=root.resolve(),
                env=run_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(30, min(120, command_timeout_seconds)),
                shell=False,
            )
            return json.dumps(
                {
                    "exit_code": result.returncode,
                    "stdout": result.stdout[-12000:],
                    "stderr": result.stderr[-12000:],
                },
                ensure_ascii=False,
            )
        if name in {"search_files", "grep"}:
            raw_pattern = str(args.get("pattern") or args.get("query") or "").strip()
            if not raw_pattern:
                return "搜索词不能为空。"
            case_insensitive = bool(args.get("case_insensitive", True))
            include_glob = str(args.get("include", "")).strip()
            flags = re.IGNORECASE if case_insensitive else 0
            try:
                regex = (
                    re.compile(raw_pattern, flags)
                    if name == "grep"
                    else re.compile(re.escape(raw_pattern), re.IGNORECASE)
                )
            except re.error:
                regex = re.compile(re.escape(raw_pattern), flags)
            matches = []
            for path in _files(root, str(args.get("subdirectory", "")).strip()):
                rel = path.relative_to(root.resolve()).as_posix()
                if include_glob and not (
                    fnmatch.fnmatch(rel, include_glob) or fnmatch.fnmatch(path.name, include_glob)
                ):
                    continue
                try:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        continue
                    lines = path.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                for number, line in enumerate(lines, 1):
                    if regex.search(line):
                        matches.append(
                            {
                                "path": rel,
                                "line": number,
                                "text": line[:400],
                            }
                        )
                        if len(matches) >= MAX_RESULTS:
                            return json.dumps(
                                {"matches": matches, "truncated": True}, ensure_ascii=False
                            )
            return json.dumps({"matches": matches, "truncated": False}, ensure_ascii=False)
        if name == "web_search":
            return execute_web_search(
                str(args.get("query", "")), int(args.get("max_results", 6) or 6)
            )
        if name == "web_fetch":
            return execute_web_fetch(
                str(args.get("url", "")), int(args.get("max_chars", 12000) or 12000)
            )
        if name in {
            "memory_store",
            "memory_search",
            "memory_update",
            "memory_delete",
            "core_memory_append",
            "core_memory_replace",
            "archival_memory_insert",
            "archival_memory_search",
            "recall_memory_search",
        }:
            mem_os = MemoryOS(workspace_root=root.resolve(), global_home=skills_home)
            if name == "core_memory_append":
                res = mem_os.core_memory_append(
                    str(args.get("label") or ""), str(args.get("content") or "")
                )
                return json.dumps({"status": "ok", "core_memory": res}, ensure_ascii=False)
            if name == "core_memory_replace":
                res = mem_os.core_memory_replace(
                    str(args.get("label") or ""),
                    str(args.get("old_content") or ""),
                    str(args.get("new_content") or ""),
                )
                return json.dumps({"status": "ok", "core_memory": res}, ensure_ascii=False)
            if name == "archival_memory_insert":
                res = mem_os.archival_memory_insert(
                    str(args.get("content") or ""),
                    tags=args.get("tags") if isinstance(args.get("tags"), list) else None,
                )
                return json.dumps({"status": "ok", "archival_memory": res}, ensure_ascii=False)
            if name == "archival_memory_search":
                archival_results = mem_os.archival_memory_search(
                    str(args.get("query") or ""),
                    limit=int(args.get("limit") or 5),
                )
                return json.dumps({"results": archival_results}, ensure_ascii=False)
            if name == "recall_memory_search":
                recall_results = mem_os.recall_memory_search(
                    str(args.get("query") or ""),
                    limit=int(args.get("limit") or 5),
                )
                return json.dumps({"results": recall_results}, ensure_ascii=False)
            if name == "memory_store":
                content_val = str(args.get("content", "")).strip()
                core_block = str(args.get("core_block", "")).strip()
                if core_block:
                    core_res = mem_os.update_core_memory(core_block, content_val, mode="append")
                    return json.dumps(
                        {"status": "ok", "message": "已成功存储记忆", "core_memory": core_res},
                        ensure_ascii=False,
                    )
                stored = mem_os.store_memory(
                    content_val,
                    category=str(args.get("category") or "fact"),
                    importance=int(args.get("importance") or 3),
                    tags=args.get("tags") if isinstance(args.get("tags"), list) else None,
                )
                return json.dumps(
                    {"status": "ok", "message": "已成功存储记忆", "memory": stored},
                    ensure_ascii=False,
                )
            if name == "memory_search":
                found = mem_os.search_memories(
                    str(args.get("query") or ""),
                    category=str(args.get("category")) if args.get("category") else None,
                    limit=int(args.get("limit") or 8),
                )
                return json.dumps(found, ensure_ascii=False)
            if name == "memory_update":
                updated = mem_os.update_memory(
                    str(args.get("memory_id") or ""),
                    str(args.get("content") or ""),
                    importance=int(args["importance"]) if "importance" in args else None,
                )
                return json.dumps({"status": "ok", "memory": updated}, ensure_ascii=False)
            if name == "memory_delete":
                deleted = mem_os.delete_memory(str(args.get("target") or ""))
                return json.dumps({"status": "ok", **deleted}, ensure_ascii=False)
        return "工具不存在。"
    except subprocess.TimeoutExpired:
        return json.dumps({"exit_code": 124, "stdout": "", "stderr": "命令运行超过 120 秒上限"})
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
        return f"读取工具未能完成：{error}"


def list_workspace_files(root: Path, subdirectory: str = "") -> list[dict[str, Any]]:
    """Return a bounded project tree with directories before their children."""
    base = root.resolve(strict=True)
    folder = (base / subdirectory).resolve(strict=True) if subdirectory else base
    if not folder.is_relative_to(base) or not folder.is_dir():
        raise ValueError("目录必须位于项目内")
    result: list[dict[str, Any]] = []
    try:
        for path in sorted(
            folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold())
        ):
            try:
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(base):
                    continue
                relative = resolved.relative_to(base)
                parts = {part.casefold() for part in relative.parts}
                name = resolved.name.casefold()
                hidden_dirs = {".git", ".masp", "node_modules", ".venv", "venv", "__pycache__"}
                if parts.intersection(hidden_dirs):
                    continue
                sensitive = (
                    name.startswith(".env")
                    or name.endswith((".pem", ".key", ".p12", ".pfx"))
                    or "secret" in name
                )
                if sensitive:
                    continue
                is_directory = resolved.is_dir()
                result.append(
                    {
                        "name": resolved.name,
                        "path": relative.as_posix(),
                        "type": "directory" if is_directory else "file",
                        "size": None if is_directory else resolved.stat().st_size,
                    }
                )
            except OSError:
                continue
    except PermissionError:
        raise ValueError("没有权限读取此目录") from None
    return result[:500]
