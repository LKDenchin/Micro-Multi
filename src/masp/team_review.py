"""Execution boundary for a lead agent preparing an unapproved team plan."""

import json
from pathlib import Path
from typing import Any


def write_team_documents(root: Path, identity: str, team: dict[str, Any]) -> None:
    """Persist the exact editable revision shown in the approval card."""
    directory = root / ".masp" / "team-plans" / (identity + "-v" + str(team["version"]))
    directory.mkdir(parents=True, exist_ok=True)
    agents = team.get("agents", [])
    documents = {
        "requirements.md": "# 本轮需求\n\n" + str(team.get("requirement") or "") + "\n",
        "design.md": "# 协作设计\n\n确认后执行。按文件归属、任务依赖和验收标准协调。\n\n"
        + "```json\n"
        + json.dumps(team.get("pending_tasks", []), ensure_ascii=False, indent=2)
        + "\n```\n",
        "tasks.md": "# 完整任务与提示词\n\n"
        + "\n\n".join(
            "## "
            + str(agent.get("name") or agent["id"])
            + "\n\n负责人："
            + agent["id"]
            + "\n\n模型："
            + str(agent.get("model_profile_id") or "继承主模型")
            + "\n\n负责文件："
            + ", ".join(agent.get("owned_paths") or [])
            + "\n\n任务：\n\n"
            + str(agent.get("responsibility") or "")
            + "\n\n专属提示词：\n\n"
            + str(agent.get("system_prompt") or "")
            for agent in agents
        )
        + "\n",
    }
    for name, content in documents.items():
        (directory / name).write_text(content, encoding="utf-8")
    team["plan_documents"] = [(directory / name).relative_to(root).as_posix() for name in documents]


def planning_tool_allowed(name: str, arguments: str) -> bool:
    if name in {
        "read_file",
        "list_files",
        "search_files",
        "web_search",
        "web_fetch",
        "memory_search",
        "start_subagents",
        "create_subagent",
        "adjust_subagent",
        "remove_subagent",
        "wait_subagents",
        "dispatch_subagent_task",
        "dispatch_subagents_parallel",
    }:
        return True
    try:
        args: Any = json.loads(arguments or "{}")
        if not isinstance(args, dict):
            return False
        if name in {"write_file", "edit_file"}:
            path = str(args.get("path") or "").replace("\\", "/")
            return path.endswith(".md") and (
                path.startswith("docs/")
                or path in {"plan.md", "requirements.md", "design.md", "tasks.md"}
            )
        if name == "plugin_manager":
            return args.get("action") == "list"
    except (ValueError, TypeError):
        pass
    return False
