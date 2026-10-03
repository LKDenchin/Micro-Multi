"""Micro-Multi local extension adapters, JSON tools, MCP and Skill bundles."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, SchemaError, ValidationError, validate

from masp.code_review import ocr_engine_status
from masp.cordis_runtime import close_native_hosts, execute_native, inspect_native, native_manifest
from masp.extension_sources import acquire_bundle, discard_source, remote_source
from masp.mcp_bridge import discover_project_mcp_servers
from masp.mcp_connections import invalidate_connections
from masp.mcp_server import BUILTIN_MCP_SERVER_ID, builtin_mcp_server_record, builtin_mcp_tools
from masp.skills import MAX_SKILL_BYTES, list_skills
from masp.storage import Store, identifier, now

DEFAULT_DSH_SETTINGS: dict[str, Any] = {
    "id": "global",
    "general": {
        "locale": "zh-CN",
        "autoApproveRead": True,
        "restoreLastSession": False,
        "defaultBranch": "main",
        "sendWithEnter": True,
        "linkProjects": True,
    },
    "workspace": {
        "defaultBranch": "main",
        "autoInitGit": True,
        "linkProjects": True,
    },
    "context": {
        "maxContextTokens": 64000,
        "autoCompact": True,
    },
    "review": {
        "defaultMode": "adaptive",
        "engine": "@alibaba-group/open-code-review",
        "repository": "https://github.com/alibaba/open-code-review",
    },
    "agentPreset": {
        "name": "Micro-Multi 主控架构师",
        "role": "负责理解用户需求、拆解多 Agent 协作任务、调度工具并审查最终改动。",
        "instructions": "始终优先保持代码最小改动、契约先行与可验证性。",
        "template": "architect",
    },
    "permissions": {
        "defaultMode": "commands",
        "blockDestructiveGit": True,
        "isolateSubagentWorktree": True,
        "requireTeamConfirmation": True,
    },
    "shell": {
        "enabled": True,
        "defaultShell": "powershell" if os.name == "nt" else "bash",
        "timeoutSeconds": 120,
        "loginShell": False,
    },
    "agentLoop": {
        "enabled": True,
        "runtime": "python",
        "maxToolSteps": 30,
        "autonomousHours": 8,
        "recoveryMaxAttempts": 2,
    },
    "subagent": {
        "enabled": True,
        "maxConcurrent": 2,
        "maxDepth": 2,
    },
    "webSearch": {
        "enabled": True,
        "provider": "duckduckgo",
        "maxResults": 5,
        "allowedDomains": [],
        "blockedDomains": [],
    },
    "theme": {
        "mode": "dark",
        "accent": "slate",
        "compactDensity": False,
    },
    "shortcuts": {
        "globalSearch": "Ctrl+K",
        "newChat": "Ctrl+N",
        "openSettings": "Ctrl+,",
        "sendMessage": "Enter",
    },
    "sessionLog": {
        "enabled": True,
        "retentionDays": 30,
        "includeToolPayloads": True,
    },
    "pluginInventory": {
        "@alibaba-group/open-code-review": True,
        "@deepseek-harness/shell": True,
        "@deepseek-harness/agent-loop": True,
        "@deepseek-harness/subagent": True,
        "@deepseek-harness/web-search": True,
        "@masp/workspace-mcp": True,
    },
}


def get_dsh_settings(store: Store) -> dict[str, Any]:
    merged: dict[str, Any] = json.loads(json.dumps(DEFAULT_DSH_SETTINGS))
    try:
        saved = store.get("dsh_setting", "global")
        for key, value in saved.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
    except KeyError:
        pass
    if merged["agentPreset"].get("name") in {"MASP", "MASP 主控架构师", "MASP主控架构师"}:
        merged["agentPreset"]["name"] = "Micro-Multi 主控架构师"
    hours = float(merged["agentLoop"].get("autonomousHours") or 8)
    merged["agentLoop"]["autonomousHours"] = next(
        (tier for tier in (0.5, 1, 2, 4, 8) if tier >= hours), 8
    )
    value = int(merged["context"].get("maxContextTokens") or 64000)
    merged["context"]["maxContextTokens"] = next(
        (tier for tier in (32000, 64000, 128000, 256000) if tier >= value), 256000
    )
    return merged


def save_dsh_settings(store: Store, patch: dict[str, Any]) -> dict[str, Any]:
    current = get_dsh_settings(store)
    for key, value in patch.items():
        if key == "id":
            continue
        if isinstance(value, dict) and isinstance(current.get(key), dict):
            current[key] = {**current[key], **value}
        else:
            current[key] = value
    # Keep general.defaultBranch and workspace.defaultBranch synchronized
    if isinstance(patch.get("general"), dict) and "defaultBranch" in patch["general"]:
        current.setdefault("workspace", {})["defaultBranch"] = patch["general"]["defaultBranch"]
    elif isinstance(patch.get("workspace"), dict) and "defaultBranch" in patch["workspace"]:
        current.setdefault("general", {})["defaultBranch"] = patch["workspace"]["defaultBranch"]
    if isinstance(patch.get("general"), dict) and "linkProjects" in patch["general"]:
        current.setdefault("workspace", {})["linkProjects"] = patch["general"]["linkProjects"]
    elif isinstance(patch.get("workspace"), dict) and "linkProjects" in patch["workspace"]:
        current.setdefault("general", {})["linkProjects"] = patch["workspace"]["linkProjects"]
    current["id"] = "global"
    current["updated_at"] = now()
    return store.put("dsh_setting", current)


def official_dsh_plugins(store: Store) -> list[dict[str, Any]]:
    settings = get_dsh_settings(store)
    inventory = settings.get("pluginInventory", {})
    ocr_info = ocr_engine_status()
    return [
        {
            "id": "@alibaba-group/open-code-review",
            "name": "Alibaba Open Code Review (默认代码审查引擎)",
            "package": "@alibaba-group/open-code-review",
            "repository": "https://github.com/alibaba/open-code-review",
            "category": "official",
            "kind": "code-review",
            "version": "1.12.10",
            "description": (
                "已加载 https://github.com/alibaba/open-code-review 官方引擎"
                f" ({'二进制已就绪: ' + Path(ocr_info['binary']).name if ocr_info.get('loaded') else '待安装'})，"
                "作为应用默认代码审查方式。"
            ),
            "enabled": bool(inventory.get("@alibaba-group/open-code-review", True)),
            "settings_key": "review",
            "config": {**settings.get("review", {}), **ocr_info},
            "components": [
                {
                    "id": "engine:opencodereview",
                    "type": "binary",
                    "name": "opencodereview",
                    "enabled": bool(ocr_info.get("loaded", True)),
                },
                {
                    "id": "review:default-mode",
                    "type": "service",
                    "name": "默认审查: open-code-review",
                    "enabled": True,
                },
            ],
        },
        {
            "id": "@deepseek-harness/shell",
            "name": "Shell 执行环境",
            "package": "@deepseek-harness/ui-settings-shell",
            "category": "official",
            "kind": "runtime",
            "version": "0.2.0",
            "description": "配置受控终端命令执行器、超时时间与默认 Shell 环境。",
            "enabled": bool(inventory.get("@deepseek-harness/shell", True)),
            "settings_key": "shell",
            "config": settings.get("shell", {}),
            "components": [
                {"id": "tool:run_command", "type": "tool", "name": "run_command", "enabled": True},
                {
                    "id": "settings:shell",
                    "type": "settings",
                    "name": "Shell 设置面板",
                    "enabled": True,
                },
            ],
        },
        {
            "id": "@deepseek-harness/agent-loop",
            "name": "智能体执行循环 (Agent Loop)",
            "package": "@deepseek-harness/ui-settings-agent-loop",
            "category": "official",
            "kind": "orchestrator",
            "version": "0.2.0",
            "description": "管理主 Agent 单轮最大工具调用步数与异常自动恢复重试策略。",
            "enabled": bool(inventory.get("@deepseek-harness/agent-loop", True)),
            "settings_key": "agentLoop",
            "config": settings.get("agentLoop", {}),
            "components": [
                {
                    "id": "loop:controller",
                    "type": "service",
                    "name": "Loop Controller",
                    "enabled": True,
                },
                {
                    "id": "settings:agent-loop",
                    "type": "settings",
                    "name": "循环策略设置",
                    "enabled": True,
                },
            ],
        },
        {
            "id": "@deepseek-harness/subagent",
            "name": "多智能体并发与子 Agent 调度",
            "package": "@deepseek-harness/ui-settings-subagent",
            "category": "official",
            "kind": "multi-agent",
            "version": "0.2.0",
            "description": (
                "配置子 Agent 最大并行数（支持 1-4 及自定义 >4）、嵌套深度与独立 Worktree 隔离。"
            ),
            "enabled": bool(inventory.get("@deepseek-harness/subagent", True)),
            "settings_key": "subagent",
            "config": settings.get("subagent", {}),
            "components": [
                {
                    "id": "tool:configure_team",
                    "type": "tool",
                    "name": "configure_team",
                    "enabled": True,
                },
                {"id": "tool:start_team", "type": "tool", "name": "start_team", "enabled": True},
                {
                    "id": "settings:subagent",
                    "type": "settings",
                    "name": "子智能体并发设置",
                    "enabled": True,
                },
            ],
        },
        {
            "id": "@deepseek-harness/web-search",
            "name": "联网搜索与文档检索",
            "package": "@deepseek-harness/ui-settings-web-search",
            "category": "official",
            "kind": "tool",
            "version": "0.2.0",
            "description": "配置搜索提供商、返回结果数量上限及域名白名单/黑名单。",
            "enabled": bool(inventory.get("@deepseek-harness/web-search", True)),
            "settings_key": "webSearch",
            "config": settings.get("webSearch", {}),
            "components": [
                {
                    "id": "settings:web-search",
                    "type": "settings",
                    "name": "搜索策略配置",
                    "enabled": True,
                },
            ],
        },
        {
            "id": "@masp/workspace-mcp",
            "name": "Micro-Multi 工作区内置 MCP 服务",
            "package": "@masp/workspace-mcp",
            "category": "official",
            "kind": "mcp",
            "version": "0.2.0",
            "description": (
                "开箱即用的工作区 MCP 服务器，提供 Git 状态、Diff、文件树浏览与代码搜索工具。"
            ),
            "enabled": bool(inventory.get("@masp/workspace-mcp", True)),
            "settings_key": "workspaceMcp",
            "server_id": BUILTIN_MCP_SERVER_ID,
            "config": builtin_mcp_server_record(
                enabled=bool(inventory.get("@masp/workspace-mcp", True))
            ),
            "components": [
                {
                    "id": f"mcp:{tool['name']}",
                    "type": "mcp-tool",
                    "name": tool["name"],
                    "description": tool["description"],
                    "enabled": True,
                }
                for tool in builtin_mcp_tools()
            ],
        },
    ]


def parse_dsh_manifest_dir(folder: Path) -> dict[str, Any] | None:
    """Inspect a directory for DeepSeek-Harness / Cordis / Claude / MCP / Skill plugin manifests."""
    if not folder.is_dir():
        return None
    resolved = folder.resolve()
    name = resolved.name
    description = ""
    version = "0.1.0"
    kind = "bundle"
    components: list[dict[str, Any]] = []
    tools_found: list[dict[str, Any]] = []
    mcp_found: list[dict[str, Any]] = []
    skills_found: list[dict[str, Any]] = []

    pkg_file = resolved / "package.json"
    if pkg_file.is_file():
        try:
            pkg = json.loads(pkg_file.read_text(encoding="utf-8"))
            if isinstance(pkg, dict):
                name = str(pkg.get("name") or name)
                description = str(pkg.get("description") or description)
                version = str(pkg.get("version") or version)
                dsh_meta = pkg.get("deepseek-harness") or pkg.get("dsh") or pkg.get("cordis") or {}
                if isinstance(dsh_meta, dict):
                    kind = str(dsh_meta.get("kind") or dsh_meta.get("type") or "dsh-plugin")
                    description = str(dsh_meta.get("description") or description)
                    for tool_spec in dsh_meta.get("tools", []):
                        if isinstance(tool_spec, dict) and tool_spec.get("name"):
                            tools_found.append(tool_spec)
                            components.append(
                                {
                                    "id": f"tool:{tool_spec['name']}",
                                    "type": "tool",
                                    "name": str(tool_spec["name"]),
                                    "enabled": True,
                                }
                            )
        except (OSError, ValueError, TypeError):
            pass

    for manifest_rel in ("plugin.json", ".claude-plugin/plugin.json", "bundle.json"):
        manifest_path = resolved / manifest_rel
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(manifest, dict):
                    name = str(manifest.get("name") or name)
                    description = str(manifest.get("description") or description)
                    version = str(manifest.get("version") or version)
                    kind = (
                        "claude-plugin" if ".claude-plugin" in manifest_rel else "plugin-manifest"
                    )
                    for tool_spec in manifest.get("tools", []):
                        if isinstance(tool_spec, dict) and tool_spec.get("name"):
                            tools_found.append(tool_spec)
                            components.append(
                                {
                                    "id": f"tool:{tool_spec['name']}",
                                    "type": "tool",
                                    "name": str(tool_spec["name"]),
                                    "enabled": True,
                                }
                            )
            except (OSError, ValueError, TypeError):
                pass

    for cordis_name in ("cordis.patch.yml", "cordis.yml", "cordis.yaml"):
        cordis_file = resolved / cordis_name
        if cordis_file.is_file():
            kind = "cordis-bundle"
            try:
                raw_lines = cordis_file.read_text(encoding="utf-8").splitlines()
                for line in raw_lines:
                    stripped = line.strip()
                    if stripped.startswith("- ") or stripped.endswith(":"):
                        token = stripped.lstrip("- ").rstrip(":").strip()
                        if token and not token.startswith("#") and len(token) < 80:
                            components.append(
                                {
                                    "id": f"cordis:{token}",
                                    "type": "cordis-plugin",
                                    "name": token,
                                    "enabled": True,
                                }
                            )
            except OSError:
                pass

    # Claude marketplaces declare their local plugin roots. Discover only those
    # explicit, confined directories rather than recursively scanning a repo.
    mcp_roots = [resolved]
    marketplace = resolved / ".claude-plugin" / "marketplace.json"
    if marketplace.is_file():
        if marketplace.is_symlink() or marketplace.stat().st_size > 1_000_000:
            raise ValueError("Marketplace manifest exceeds size limit or uses a symlink")
        manifest = json.loads(marketplace.read_text(encoding="utf-8"))
        entries = manifest.get("plugins", []) if isinstance(manifest, dict) else []
        if not isinstance(entries, list) or len(entries) > 100:
            raise ValueError("Marketplace must contain at most 100 local plugin entries")
        for entry in entries:
            source = entry.get("source") if isinstance(entry, dict) else None
            if isinstance(source, str) and source.startswith("./"):
                child = (resolved / source).resolve()
                if not child.is_relative_to(resolved) or child.is_symlink():
                    raise ValueError("Marketplace plugin source escapes its directory")
                if child.is_dir():
                    mcp_roots.append(child)
    declared_mcp = {}
    for mcp_root in mcp_roots:
        for server in discover_project_mcp_servers(mcp_root):
            if server["name"] in declared_mcp:
                raise ValueError(f"Duplicate MCP server name: {server['name']}")
            declared_mcp[server["name"]] = server
    for mcp_srv in declared_mcp.values():
        mcp_found.append(mcp_srv)
        components.append(
            {
                "id": f"mcp:{mcp_srv['name']}",
                "type": "mcp",
                "name": mcp_srv["name"],
                "enabled": mcp_srv.get("enabled", True),
            }
        )

    skill_files = []
    if (resolved / "SKILL.md").is_file():
        skill_files.append(resolved / "SKILL.md")
    skills_dir = resolved / "skills"
    if skills_dir.is_dir():
        skill_files.extend(skills_dir.glob("*/SKILL.md"))
    if len(skill_files) > 1000:
        raise ValueError("单个插件包最多支持 1000 个 Skill")
    for skill_file in skill_files:
        skill_name = skill_file.parent.name if skill_file.parent != resolved else resolved.name
        try:
            if skill_file.is_symlink() or skill_file.stat().st_size > MAX_SKILL_BYTES:
                raise ValueError("技能文件超过大小上限或使用了符号链接")
            text = skill_file.read_text(encoding="utf-8")
            declared_name = re.search(
                r"^name:\s*([a-z0-9][a-z0-9_-]{0,63})\s*$", text[:4000], re.MULTILINE
            )
            if declared_name:
                skill_name = declared_name.group(1)
        except OSError:
            continue
        skills_found.append({"name": skill_name, "content": text, "path": str(skill_file)})
        components.append(
            {
                "id": f"skill:{skill_name}",
                "type": "skill",
                "name": skill_name,
                "enabled": True,
            }
        )

    if not (pkg_file.is_file() or components or tools_found or mcp_found or skills_found):
        return None

    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", name.strip()).strip("-") or "dsh-bundle"
    return {
        "id": f"bundle-{slug[:48]}",
        "name": name,
        "description": description or f"本地扩展包：{resolved.name}",
        "version": version,
        "kind": kind,
        "category": "installed",
        "source_path": str(resolved),
        "enabled": True,
        "components": components,
        "tools": tools_found,
        "mcp_servers": mcp_found,
        "skills": skills_found,
    }


def _copy_skill_resources(source: Path, destination: Path) -> None:
    """Preserve relative references without following links or copying unbounded trees."""
    planned: list[tuple[Path, Path]] = []
    total = 0
    for directory, folders, files in os.walk(source):
        folders[:] = [
            name for name in folders if name not in {".git", "node_modules", ".venv", "__pycache__"}
        ]
        for name in folders:
            if (Path(directory) / name).is_symlink():
                raise ValueError("技能资源不能包含符号链接")
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("技能资源不能包含符号链接")
            total += path.stat().st_size
            if len(planned) >= 1000 or total > 32 * 1024 * 1024:
                raise ValueError("技能资源超过 1000 个文件或 32 MB 上限")
            planned.append((path, destination / path.relative_to(source)))
    for original, target in planned:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)


def _install_dsh_plugin_from_path(store: Store, home: Path, source_path: str) -> dict[str, Any]:
    target = Path(source_path).expanduser()
    if source_path.startswith(("http://", "https://")):
        raise ValueError(
            "当前加载器接受本地 JSON 工具、MCP 或 Skill 扩展包；不能将远程网址当作本地目录。原生 Cordis/DSH 插件需要 Harness 运行时。"
        )
    if not target.exists():
        raise ValueError(f"找不到指定的插件路径：{source_path}")
    if target.is_symlink():
        raise ValueError("插件目录不能使用符号链接")
    if target.is_file() and target.suffix.lower() == ".json":
        data = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("command") and data.get("name"):
            parameters = data.get("parameters", {"type": "object", "properties": {}})
            if not isinstance(parameters, dict) or parameters.get("type") != "object":
                raise ValueError("Plugin parameters must describe an object")
            if not isinstance(data.get("args", []), list):
                raise ValueError("Plugin args must be an array")
            Draft202012Validator.check_schema(parameters)
            record = {
                "id": identifier("plugin"),
                "name": str(data["name"]),
                "description": str(data.get("description") or data["name"]),
                "command": str(data["command"]),
                "args": data.get("args", []),
                "parameters": parameters,
                "enabled": bool(data.get("enabled", True)),
                "cwd": str(target.parent.resolve()),
                "source_path": str(target.resolve()),
                "created_at": now(),
                "updated_at": now(),
            }
            return store.put("plugin", record)
    root = target.parent if target.is_file() else target
    for manifest in (
        "package.json",
        "plugin.json",
        "bundle.json",
        ".claude-plugin/plugin.json",
        "cordis.patch.yml",
        "cordis.yml",
        "cordis.yaml",
        ".mcp.json",
        "mcp.json",
    ):
        file = root / manifest
        if file.is_file() and (file.is_symlink() or file.stat().st_size > 1_000_000):
            raise ValueError("插件清单超过 1 MB 上限或使用了符号链接")
    parsed = parse_dsh_manifest_dir(root)
    if parsed is None:
        raise ValueError("目录中未检测到 JSON 工具、MCP 或 SKILL.md 扩展清单")
    native = native_manifest(root)
    native_inventory = inspect_native(home, native, store, parsed["id"]) if native else None
    if native_inventory:
        for tool in native_inventory["tools"]:
            parsed["tools"].append(
                {
                    **tool,
                    "runtime": "native-cordis-host",
                    "native_manifest": native,
                    "native_tool": tool["name"],
                    "enabled": True,
                }
            )
        parsed["components"].extend(
            {
                "id": "cordis:" + item["name"],
                "name": item["name"],
                "type": "native-cordis",
                "enabled": True,
            }
            for item in native_inventory["plugins"]
        )
        parsed["kind"] = "native-cordis-host"
    if not (native_inventory or parsed["tools"] or parsed["mcp_servers"] or parsed["skills"]):
        raise ValueError(
            "该包没有可加载的原生 Cordis Host 入口、JSON 工具、MCP 或 Skill；仅 Client 界面插件暂不支持，不能标记为已加载。"
        )
    if (
        len(parsed["tools"]) > 100
        or len(parsed["skills"]) > 1000
        or len(parsed["mcp_servers"]) > 100
    ):
        raise ValueError("单个插件包最多支持 100 个工具、100 个 MCP 服务和 1000 个 Skill")
    root = root.resolve()
    bundle_id = parsed["id"]
    # Validate all runnable components before changing the inventory.
    for tool in parsed["tools"]:
        if tool.get("runtime") != "native-cordis-host" and not tool.get("command"):
            raise ValueError(
                f"工具 {tool['name']} 缺少 command；不支持直接执行 Cordis JavaScript 服务"
            )
        parameters = tool.get("parameters", {"type": "object", "properties": {}})
        if not isinstance(parameters, dict) or not isinstance(tool.get("args", []), list):
            raise ValueError("Plugin schema must be an object and args must be an array")
        Draft202012Validator.check_schema(parameters)
        if parameters.get("type") != "object":
            raise ValueError("Plugin parameters must describe an object")
    for skill in parsed["skills"]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", skill["name"]):
            raise ValueError(f"Invalid skill name: {skill['name']}")
    previous_ids = {
        item["id"]
        for table in ("plugin", "mcp_server")
        for item in store.list(table)
        if item.get("bundle_id") == bundle_id
    }
    pending: list[tuple[str, dict[str, Any], str]] = []
    deletes: list[tuple[str, str]] = []
    component_ids: list[str] = []
    resource_root = home / "extension-skills" / bundle_id / uuid.uuid4().hex
    for skill in parsed["skills"]:
        destination = resource_root / skill["name"]
        try:
            owner = store.get("skill_owner", skill["name"])
        except KeyError:
            owner = {}
        if owner and owner.get("bundle_id") != bundle_id and not owner.get("removed"):
            raise ValueError(f"技能名称已存在：{skill['name']}，请重命名后安装")
        _copy_skill_resources(Path(skill["path"]).parent, destination)
        pending.append(
            (
                "skill_owner",
                {
                    "id": skill["name"],
                    "bundle_id": bundle_id,
                    "path": str(destination / "SKILL.md"),
                },
                "",
            )
        )
    for table, components in (("mcp_server", parsed["mcp_servers"]), ("plugin", parsed["tools"])):
        for component in components:
            record_id = (
                table
                + "-"
                + hashlib.sha256((bundle_id + ":" + component["name"]).encode()).hexdigest()[:16]
            )
            item = {
                **component,
                "id": record_id,
                "bundle_id": bundle_id,
                "cwd": str(component.get("cwd") or root),
                "enabled": bool(component.get("enabled", True)),
                "created_at": now(),
                "updated_at": now(),
            }
            if table == "plugin":
                item.setdefault("description", item["name"])
                item.setdefault("args", [])
                item.setdefault("parameters", {"type": "object", "properties": {}})
            item["command"] = str(item.get("command", "")).replace(
                "${CLAUDE_PLUGIN_ROOT}", str(root)
            )
            item["args"] = [
                str(arg).replace("${CLAUDE_PLUGIN_ROOT}", str(root)) for arg in item.get("args", [])
            ]
            if isinstance(item.get("env"), dict):
                item["env"] = {
                    k: str(v).replace("${CLAUDE_PLUGIN_ROOT}", str(root))
                    for k, v in item["env"].items()
                }
            pending.append((table, item, ""))
            component_ids.append(record_id)
    for table in ("plugin", "mcp_server"):
        for item in store.list(table):
            if item["id"] in previous_ids and item["id"] not in component_ids:
                deletes.append((table, item["id"]))
    record = {
        key: parsed[key]
        for key in ("id", "name", "description", "version", "kind", "source_path", "components")
    }
    record.update(
        category="installed",
        enabled=True,
        component_ids=component_ids,
        skill_names=[skill["name"] for skill in parsed["skills"]],
        runtime="native-cordis-host" if native_inventory else "micro-multi-adapter",
        native_versions=native_inventory["versions"] if native_inventory else None,
        native_manifest=native,
        created_at=now(),
        updated_at=now(),
    )
    new_skill_names = set(record["skill_names"])
    deletes.extend(
        ("skill_owner", item["id"])
        for item in store.list("skill_owner")
        if item.get("bundle_id") == bundle_id and item["id"] not in new_skill_names
    )
    pending.append(("dsh_bundle", record, ""))
    close_native_hosts(store, bundle_id)
    store.apply_batch(pending, deletes)
    return record


def install_dsh_plugin_from_path(store: Store, home: Path, source_path: str) -> dict[str, Any]:
    stage = None
    original_source = source_path
    try:
        if remote_source(source_path):
            root, stage = acquire_bundle(home, source_path)
            source_path = str(root)
        return _install_dsh_plugin_from_path(store, home, source_path)
    except SchemaError as error:
        if stage:
            discard_source(home, stage)
        raise ValueError(f"Invalid plugin schema: {error.message[:200]}") from None
    except Exception:
        if stage:
            import sys

            from masp.extension_builds import prepare_build

            try:
                pending = prepare_build(
                    store, home, root, stage, original_source, str(sys.exception())
                )
            except (ValueError, OSError):
                discard_source(home, stage)
                raise
            if pending:
                return pending
            discard_source(home, stage)
        raise


def set_extension_enabled(store: Store, extension_id: str, enabled: bool) -> dict[str, Any]:
    if extension_id.startswith("@"):
        if extension_id not in {item["id"] for item in official_dsh_plugins(store)}:
            raise ValueError("Unknown built-in extension")
        settings = get_dsh_settings(store)
        inventory = dict(settings.get("pluginInventory", {}))
        inventory[extension_id] = enabled
        save_dsh_settings(store, {"pluginInventory": inventory})
        return {"id": extension_id, "enabled": enabled, "kind": "builtin"}
    for table in ("plugin", "dsh_bundle", "mcp_server"):
        try:
            item = store.get(table, extension_id)
        except KeyError:
            continue
        if table == "dsh_bundle" and item.get("kind") == "native-profile":
            from masp.native_profiles import save_profile as save_native_profile

            if enabled:
                directory = Path(item["source_path"])
                save_native_profile(
                    store,
                    store.path.parent,
                    item["profile_name"],
                    (directory / "cordis.yml").read_text("utf-8"),
                    (directory / "cordis.patch.yml").read_text("utf-8"),
                )
                return store.get(table, item["id"])
            try:
                active = store.get("native_profile", "active")
            except KeyError:
                active = {}
            if active.get("name") == item.get("profile_name"):
                store.delete("native_profile", "active")
                close_native_hosts(store)
        updated = store.update(table, item["id"], enabled=enabled, updated_at=now())
        if not enabled:
            for server in store.list("mcp_server"):
                if server["id"] == extension_id or server.get("bundle_id") == extension_id:
                    invalidate_connections(server["id"])
        if not enabled and (table == "dsh_bundle" or item.get("runtime") == "native-cordis-host"):
            close_native_hosts(store, item["id"] if table == "dsh_bundle" else item["bundle_id"])
        return updated
    raise ValueError("Unknown extension")


def remove_extension_bundle(store: Store, bundle_id: str) -> None:
    bundle = store.get("dsh_bundle", bundle_id)
    if bundle.get("kind") == "native-profile":
        try:
            active = store.get("native_profile", "active")
        except KeyError:
            active = {}
        if active.get("name") == bundle.get("profile_name"):
            store.delete("native_profile", "active")
            close_native_hosts(store)
    deletes = [("dsh_bundle", bundle_id)]
    for table in ("plugin", "mcp_server"):
        deletes.extend(
            (table, item["id"]) for item in store.list(table) if item.get("bundle_id") == bundle_id
        )
    owners = [
        ("skill_owner", {**owner, "removed": True}, owner["id"])
        for owner in store.list("skill_owner")
        if owner.get("bundle_id") == bundle_id
    ]
    for table, record_id in deletes:
        if table == "mcp_server":
            invalidate_connections(record_id)
    store.apply_batch(owners, deletes)
    close_native_hosts(store, bundle_id)


def manage_extension(
    store: Store, home: Path, root: Path, name: str, arguments: str
) -> dict[str, Any]:
    args = json.loads(arguments or "{}")
    if not isinstance(args, dict) or len(arguments) > 16000:
        raise ValueError("Plugin manager arguments must be a bounded object")
    if "enabled" in args and not isinstance(args["enabled"], bool):
        raise ValueError("enabled must be a boolean")
    action = str(args.get("action", "enable") if name == "plugin_manager" else "enable").casefold()
    action = {
        "list_plugins": "list",
        "list_bundles": "list",
        "install_bundle": "install",
        "set_plugin": "set",
        "set_bundle": "set",
        "remove_bundle": "remove",
    }.get(action, action)
    target = str(args.get("path") or args.get("target") or args.get("name") or "").strip()
    if action in {"list", "reload"}:
        inventory = list_all_loaded_plugins(store, home, root)
        offset = max(0, int(args.get("offset", 0)))
        limit = max(1, min(100, int(args.get("limit", 25))))
        fields = {
            "id",
            "name",
            "description",
            "version",
            "kind",
            "enabled",
            "runtime",
            "connection_status",
            "last_error",
            "scope",
            "bundle_id",
        }
        counts = {}
        next_offsets = {}
        for category in (
            "official",
            "installed",
            "tool_plugins",
            "bundles",
            "mcp_servers",
            "skills",
        ):
            items = inventory[category]
            if target:
                items = [
                    item
                    for item in items
                    if target.casefold() in str(item.get("name") or item.get("id") or "").casefold()
                ]
            counts[category] = len(items)
            inventory[category] = [
                {key: value for key, value in item.items() if key in fields}
                for item in items[offset : offset + limit]
            ]
            if len(items) > offset + limit:
                next_offsets[category] = offset + limit
        return {
            "status": "complete",
            "inventory": inventory,
            "counts": counts,
            "offset": offset,
            "limit": limit,
            "next_offsets": next_offsets,
        }
    path = Path(target).expanduser()
    if not path.is_absolute() and not target.startswith(("http://", "https://")):
        path = root / path
    if action == "install" or (target and path.exists() and action == "enable"):
        installed = install_dsh_plugin_from_path(
            store,
            home,
            target
            if remote_source(target) or target.startswith(("http://", "https://"))
            else str(path),
        )
        if installed.get("status") == "build_required":
            return installed
        summary: dict[str, Any] = {
            key: installed[key]
            for key in ("id", "name", "version", "kind", "enabled", "runtime")
            if key in installed
        }
        summary["skill_count"] = len(installed.get("skill_names", []))
        summary["component_count"] = len(installed.get("components", []))
        summary["connection_status"] = (
            "unverified"
            if any(item.get("type") == "mcp" for item in installed.get("components", []))
            else "not_required"
        )
        return {
            "status": "complete",
            "installed": summary,
            "message": "Registered plugin components; MCP dependencies and connection must be verified separately.",
        }
    if action not in {"enable", "disable", "set", "remove"}:
        raise ValueError(f"Unsupported plugin action: {action}")
    inventory = list_all_loaded_plugins(store, home, root)
    matches = [
        item
        for category in ("official", "installed", "mcp_servers")
        for item in inventory[category]
        if target.casefold() in {str(item["id"]).casefold(), str(item["name"]).casefold()}
    ]
    unique = {item["id"]: item for item in matches}
    if len(unique) != 1:
        raise ValueError(
            "未找到唯一插件，请先 list 查询精确 ID；原生 Cordis/npm 插件需要 Harness 运行时"
        )
    item = next(iter(unique.values()))
    if action == "remove":
        remove_extension_bundle(store, item["id"])
        return {"status": "complete", "removed": item["id"]}
    updated = set_extension_enabled(
        store,
        item["id"],
        bool(args.get("enabled", True)) if action == "set" else action != "disable",
    )
    return {"status": "complete", "extension": updated}


def list_all_loaded_plugins(
    store: Store, home: Path, project_root: Path | None = None
) -> dict[str, Any]:
    """Return the Micro-Multi adapter inventory (not a native Cordis runtime)."""
    official = official_dsh_plugins(store)
    tool_plugins = [
        {
            **item,
            "configured_enabled": item.get("enabled"),
            "enabled": extension_is_enabled(store, item),
        }
        for item in store.list("plugin")
    ]
    bundles = store.list("dsh_bundle")
    user_mcp = [
        {
            **item,
            "configured_enabled": item.get("enabled"),
            "enabled": extension_is_enabled(store, item),
        }
        for item in store.list("mcp_server")
    ]
    project_mcp = discover_project_mcp_servers(project_root) if project_root else []
    skills = list_skills(project_root, home)

    installed: list[dict[str, Any]] = []
    for bundle in bundles:
        installed.append(bundle)
    for item in tool_plugins:
        if item.get("bundle_id"):
            continue
        installed.append(
            {
                "id": item["id"],
                "name": item["name"],
                "description": item["description"],
                "version": "1.0.0",
                "kind": "json-tool",
                "category": "installed",
                "command": item["command"],
                "args": item["args"],
                "parameters": item["parameters"],
                "enabled": item["enabled"],
                "components": [
                    {
                        "id": f"tool:{item['id']}",
                        "type": "tool",
                        "name": item["name"],
                        "enabled": item["enabled"],
                    }
                ],
            }
        )

    builtin_mcp_enabled = any(p["id"] == "@masp/workspace-mcp" and p["enabled"] for p in official)
    all_mcp = [
        builtin_mcp_server_record(enabled=builtin_mcp_enabled),
        *user_mcp,
        *project_mcp,
    ]
    return {
        "runtime": "micro-multi-python-and-native-cordis",
        "native_cordis": {"host": True, "client": False, "cordis": "4.0.4", "tools": "0.2.0-rc.1"},
        "official": official,
        "installed": installed,
        "tool_plugins": tool_plugins,
        "bundles": bundles,
        "mcp_servers": all_mcp,
        "skills": skills,
    }


def extension_is_enabled(store: Store, extension: dict[str, Any]) -> bool:
    try:
        current = store.get(
            "plugin" if str(extension["id"]).startswith("plugin") else "mcp_server", extension["id"]
        )
    except KeyError:
        return False
    if not current.get("enabled"):
        return False
    if current.get("bundle_id"):
        try:
            return bool(store.get("dsh_bundle", current["bundle_id"]).get("enabled"))
        except KeyError:
            return False
    return True


def discover_plugins(
    store: Store,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    schemas = []
    lookup = {}
    disabled_bundles = {item["id"] for item in store.list("dsh_bundle") if not item.get("enabled")}
    for plugin in store.list("plugin"):
        if (
            not plugin["enabled"]
            or plugin.get("bundle_id") in disabled_bundles
            or (plugin.get("bundle_id") and not extension_is_enabled(store, plugin))
        ):
            continue
        alias = "plugin_" + plugin["id"].replace("-", "_")
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": alias,
                    "description": plugin["description"],
                    "parameters": plugin["parameters"],
                },
            }
        )
        lookup[alias] = plugin
    return schemas, lookup


def execute_plugin(
    plugin: dict[str, Any],
    arguments: str,
    cwd: Path,
    store: Store | None = None,
    *,
    cancel_signal: Any = None,
) -> str:
    if store is not None and not extension_is_enabled(store, plugin):
        raise ValueError("插件已禁用或移除，不能继续调用")
    if len(arguments) > 16000:
        raise ValueError("Plugin arguments are too large")
    parsed = json.loads(arguments)
    if not isinstance(parsed, dict):
        raise ValueError("Plugin arguments must be an object")
    try:
        validate(parsed, plugin["parameters"])
    except ValidationError as error:
        raise ValueError(f"Plugin arguments are invalid: {error.message[:200]}") from None
    if plugin.get("runtime") == "native-cordis-host":
        if store is None:
            raise ValueError("Native Cordis execution requires the application Store")
        return execute_native(store, plugin, arguments, cwd)
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG"}
    }
    if isinstance(plugin.get("env"), dict):
        env.update({str(key): str(value) for key, value in plugin["env"].items()})
    env["MICRO_MULTI_WORKSPACE"] = str(cwd.resolve())
    from functools import partial

    from masp.managed_commands import command_run

    runner = (
        partial(command_run, cancel_signal=cancel_signal)
        if cancel_signal is not None
        else subprocess.run
    )
    try:
        result = runner(
            [plugin["command"], *plugin["args"]],
            cwd=Path(plugin["cwd"]) if plugin.get("cwd") else cwd,
            env=env,
            input=json.dumps(parsed, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Plugin failed: {type(error).__name__}") from None
    if result.returncode:
        raise RuntimeError(f"Plugin exited with code {result.returncode}")
    return result.stdout[:12000]
