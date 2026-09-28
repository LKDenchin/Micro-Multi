"""Git workspace adapter with bounded commands and no remote push or forced overwrite."""

import os
import subprocess
from pathlib import Path
from typing import Any

from masp.domain import Proposal, TaskSpec, safe_path


class GitError(RuntimeError):
    pass


def git(root: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG",
    }}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(
        ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "commit.gpgsign=false",
         "-c", "core.autocrlf=false", "-c", "user.name=MASP Agent",
         "-c", "user.email=agent@masp.local", "-C", str(root), *args],
        capture_output=True, encoding="utf-8", errors="replace", env=env, timeout=45, check=False,
    )
    if result.returncode:
        raise GitError(f"git {args[0]} exited {result.returncode}: {result.stderr[:2000]}")
    return result.stdout.strip() if "-z" not in args else result.stdout


def target(root: Path, name: str) -> Path:
    safe_path(name)
    path = root
    for part in name.split("/"):
        path /= part
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError(f"SECURITY_BLOCK: linked path {name}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("SECURITY_BLOCK: path outside workspace")
    return path


def allowed(name: str, paths: list[str]) -> bool:
    return any(name == scope or name.startswith(scope + "/") for scope in paths)


def apply_proposal(root: Path, task: TaskSpec, proposal: Proposal) -> list[str]:
    for name in proposal.files:
        if not allowed(name, task.allowed_paths):
            raise ValueError(f"CONTRACT_ERROR: {name} outside task scope")
        target(root, name)
    for name, content in proposal.files.items():
        path = target(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return sorted(proposal.files)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=False)
    git(path, "init", "-b", "main")
    (path / "README.md").write_text("# Managed engineering project\n", encoding="utf-8")
    (path / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-m", "chore: initialize project")


def import_repo(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise ValueError("Repository must be an existing local Git directory")
    git(source, "rev-parse", "--verify", "HEAD")
    # Copy committed history only; source working tree and branches remain untouched.
    git(source, "clone", "--no-hardlinks", "--", str(source.resolve()), str(destination))


def repository_context(root: Path) -> dict[str, Any]:
    names = git(root, "ls-files", "-z").split("\0")
    # Only an explicit small documentation allowlist reaches a model by default.
    files = {}
    for name in ("README.md", "pyproject.toml"):
        if name in names:
            path = target(root, name)
            files[name] = path.read_text("utf-8", errors="replace")[:12000]
    return {"revision": git(root, "rev-parse", "HEAD"), "files": files,
            "paths": [name for name in names if name][:300]}


class Workspace:
    def __init__(self, repository: Path, run_root: Path, run_id: str, revision: str):
        self.repository = repository
        self.root = run_root
        self.run_id = run_id
        self.integration = run_root / "integration"
        self.branch = f"masp/{run_id}/integration"
        self.revision = revision

    def create(self) -> None:
        self.root.mkdir(parents=True, exist_ok=False)
        git(self.repository, "worktree", "add", "-b", self.branch,
            str(self.integration), self.revision)

    def task(self, task_id: str) -> Path:
        path = self.root / task_id
        git(self.repository, "worktree", "add", "-b", f"masp/{self.run_id}/{task_id}",
            str(path), git(self.integration, "rev-parse", "HEAD"))
        return path

    def commit(self, path: Path, task_id: str) -> str:
        git(path, "add", "--all")
        git(path, "commit", "--allow-empty", "-m", f"feat({task_id}): verified agent implementation")
        return git(path, "rev-parse", "HEAD")

    def merge(self, commit: str) -> str:
        git(self.integration, "merge", "--no-ff", "--no-edit", commit)
        return git(self.integration, "rev-parse", "HEAD")

    def diff(self) -> str:
        return git(self.integration, "diff", self.revision, "HEAD", "--")
