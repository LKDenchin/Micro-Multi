"""Project and user skill discovery for the Agent tool registry."""

import re
from pathlib import Path
from typing import Any

from masp.storage import Store

SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_SKILL_BYTES = 256_000


def _folders(project: Path | None, home: Path | None) -> list[tuple[str, Path]]:
    folders = []
    if project:
        for prefix in (".agents", ".opencode", ".claude"):
            folders.append(("project", project / prefix / "skills"))
    if home:
        folders.append(("user", home / "skills"))
    return folders


def _skill_file(folder: Path, name: str) -> Path | None:
    if not SKILL_NAME.fullmatch(name):
        return None
    directory = folder / name
    path = directory / "SKILL.md"
    if directory.is_symlink() or path.is_symlink() or not path.is_file():
        return None
    if path.stat().st_size > MAX_SKILL_BYTES:
        return None
    return path


def _installed_skills(home: Path | None) -> list[dict[str, Any]]:
    if not home or not (home / "store.sqlite3").is_file():
        return []
    store = Store(home / "store.sqlite3")
    enabled = {item["id"] for item in store.list("dsh_bundle") if item.get("enabled")}
    return [
        item
        for item in store.list("skill_owner")
        if item.get("bundle_id") in enabled and item.get("path") and not item.get("removed")
    ]


def list_skills(project: Path | None, home: Path | None = None) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for scope, folder in _folders(project, home):
        if not folder.is_dir() or folder.is_symlink():
            continue
        for directory in sorted(folder.iterdir()):
            path = _skill_file(folder, directory.name)
            if not path or directory.name in found:
                continue
            content = path.read_text("utf-8", errors="replace")
            description = ""
            match = re.search(r"^description:\s*(.+)$", content[:4000], re.MULTILINE)
            if match:
                description = match.group(1).strip().strip("'\"")
            found[directory.name] = {
                "name": directory.name,
                "description": description or content.splitlines()[0][:160],
                "scope": scope,
            }
    for item in _installed_skills(home):
        name = item["id"]
        path = Path(item["path"])
        if (
            name not in found
            and path.is_file()
            and not path.is_symlink()
            and path.stat().st_size <= MAX_SKILL_BYTES
        ):
            content = path.read_text("utf-8", errors="replace")
            match = re.search(r"^description:\s*(.+)$", content[:4000], re.MULTILINE)
            found[name] = {
                "name": name,
                "description": match.group(1).strip().strip("\"'") if match else name,
                "scope": "plugin",
                "source_path": str(path),
                "bundle_id": item["bundle_id"],
            }
    return list(found.values())


def load_skill(project: Path | None, home: Path | None, name: str) -> str:
    if not SKILL_NAME.fullmatch(name):
        raise ValueError("Invalid skill name")
    for _, folder in _folders(project, home):
        path = _skill_file(folder, name)
        if path:
            return path.read_text("utf-8")
    for item in _installed_skills(home):
        if item["id"] == name:
            path = Path(item["path"])
            if path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_SKILL_BYTES:
                return f"Skill directory: {path.parent}\n\n" + path.read_text("utf-8")
    raise ValueError(f"Unknown skill: {name}")


def save_user_skill(home: Path, name: str, content: str) -> dict[str, Any]:
    if not SKILL_NAME.fullmatch(name):
        raise ValueError("Invalid skill name")
    if not content.strip() or len(content.encode("utf-8")) > MAX_SKILL_BYTES:
        raise ValueError("Skill content must be between 1 and 256000 bytes")
    folder = home / "skills"
    if folder.exists() and folder.is_symlink():
        raise ValueError("Skill folder cannot be a symlink")
    target = folder / name
    if target.exists() and target.is_symlink():
        raise ValueError("Skill target cannot be a symlink")
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(content, encoding="utf-8")
    return {"name": name, "scope": "user", "description": content.splitlines()[0][:160]}


def read_skill_resource(project: Path | None, home: Path | None, name: str, relative: str) -> str:
    if not SKILL_NAME.fullmatch(name) or not relative or Path(relative).is_absolute():
        raise ValueError("Invalid skill resource path")
    base = None
    for _, folder in _folders(project, home):
        if _skill_file(folder, name):
            base = folder / name
            break
    if base is None:
        for item in _installed_skills(home):
            if item["id"] == name:
                base = Path(item["path"]).parent
                break
    if base is None:
        raise ValueError(f"Unknown skill: {name}")
    path = (base / relative).resolve(strict=True)
    if (
        not path.is_relative_to(base.resolve())
        or not path.is_file()
        or path.stat().st_size > MAX_SKILL_BYTES
    ):
        raise ValueError("Skill resource exceeds its directory or size limit")
    return path.read_text("utf-8")
