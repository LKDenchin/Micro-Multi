"""Git workspace adapter with bounded commands and no remote push or forced overwrite."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from masp.domain import Proposal, TaskSpec, safe_path


class GitError(RuntimeError):
    pass


def git(root: Path, *args: str) -> str:
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "LANG",
        }
    }
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(
        [
            "git",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            "-c",
            "user.name=Micro-Multi Agent",
            "-c",
            "user.email=agent@masp.local",
            "-C",
            str(root),
            *args,
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=45,
        check=False,
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


def collect_tool_edits(root: Path, task: TaskSpec, revision: str) -> dict[str, str]:
    """Include real tool/command edits in review, even if the model omits them."""
    names = set(git(root, "diff", revision, "--name-only", "-z").split("\0"))
    names.update(git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0"))
    files: dict[str, str] = {}
    total = 0
    for name in sorted(names - {""}):
        if not allowed(name, task.allowed_paths):
            raise ValueError(f"CONTRACT_ERROR: tool changed {name} outside task scope")
        path = target(root, name)
        if not path.is_file():
            raise ValueError(f"CONTRACT_ERROR: deletion is not supported by this contract: {name}")
        total += path.stat().st_size
        if total > 2_000_000 or len(files) >= 50:
            raise ValueError("CONTRACT_ERROR: tool edits exceed review size limits")
        files[name] = path.read_text(encoding="utf-8")
    return files


def init_repo(path: Path, default_branch: str = "main") -> None:
    branch = (default_branch or "main").strip() or "main"
    path.mkdir(parents=True, exist_ok=False)
    git(path, "init", "-b", branch)
    (path / "README.md").write_text("# Managed engineering project\n", encoding="utf-8")
    (path / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-m", "chore: initialize project")


def _initial_ignore(root: Path) -> None:
    ignore = root / ".gitignore"
    defaults = (
        "\n.env\n.env.*\n!.env.example\n*.pem\n*.key\n"
        "*.p12\n*.pfx\n__pycache__/\n*.pyc\nnode_modules/\n"
    )
    current = ignore.read_text("utf-8", errors="replace") if ignore.exists() else ""
    if not all(item in current for item in (".env", "*.pem", "node_modules/")):
        ignore.write_text(current.rstrip() + defaults, encoding="utf-8")


def is_repository_root(path: Path) -> bool:
    try:
        return Path(git(path, "rev-parse", "--show-toplevel")).resolve() == path.resolve()
    except GitError:
        return False


def initialize_existing_repo(path: Path, default_branch: str = "main") -> None:
    """Initialize an explicitly selected non-Git folder and create a safe base commit."""
    branch = (default_branch or "main").strip() or "main"
    git(path, "init", "-b", branch)
    _initial_ignore(path)
    git(path, "add", "--all")
    git(path, "commit", "--allow-empty", "-m", "chore: initialize Micro-Multi workspace")


def import_repo(source: Path, destination: Path, default_branch: str = "main") -> None:
    branch = (default_branch or "main").strip() or "main"
    if not source.is_dir():
        raise ValueError("所选路径必须是本地文件夹")
    if is_repository_root(source):
        git(source, "rev-parse", "--verify", "HEAD")
        # Copy committed history only; source working tree and branches remain untouched.
        git(source, "clone", "--no-hardlinks", "--", str(source.resolve()), str(destination))
        return
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".masp",
            ".env",
            ".env.*",
            "*.pem",
            "*.key",
            "*.p12",
            "*.pfx",
            "node_modules",
            "__pycache__",
            ".venv",
        ),
    )
    git(destination, "init", "-b", branch)
    _initial_ignore(destination)
    git(destination, "add", "--all")
    git(destination, "commit", "--allow-empty", "-m", "chore: import local folder")


def repository_context(root: Path, scopes: list[str] | None = None) -> dict[str, Any]:
    names = git(root, "ls-files", "-z").split("\0")
    # Only an explicit small documentation allowlist reaches a model by default.
    files: dict[str, str] = {}
    for name in ("README.md", "pyproject.toml"):
        if name in names:
            path = target(root, name)
            files[name] = path.read_text("utf-8", errors="replace")[:12000]
    if scopes:
        candidates = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        remaining = 40000
        for name in sorted(set(candidates.split("\0")) - {""}):
            if allowed(name, scopes) and remaining > 0:
                path = target(root, name)
                if path.is_file():
                    files[name] = path.read_text("utf-8", errors="replace")[:remaining]
                    remaining -= len(files[name])
    return {
        "revision": git(root, "rev-parse", "HEAD"),
        "files": files,
        "paths": [name for name in names if name][:300],
    }


class Workspace:
    def __init__(
        self,
        repository: Path,
        run_root: Path,
        run_id: str,
        revision: str,
        isolate_worktree: bool = True,
    ):
        self.repository = repository
        self.root = run_root
        self.run_id = run_id
        self.integration = run_root / "integration"
        self.branch = f"masp/{run_id}/integration"
        self.revision = revision
        self.isolate_worktree = isolate_worktree

    def create(self) -> None:
        self.root.mkdir(parents=True, exist_ok=False)
        git(
            self.repository,
            "worktree",
            "add",
            "-b",
            self.branch,
            str(self.integration),
            self.revision,
        )

    def task(self, task_id: str) -> Path:
        path = self.root / task_id
        git(
            self.repository,
            "worktree",
            "add",
            "-b",
            f"masp/{self.run_id}/{task_id}",
            str(path),
            git(self.integration, "rev-parse", "HEAD"),
        )
        return path

    def commit(self, path: Path, task_id: str) -> str:
        git(path, "add", "--all")
        git(
            path, "commit", "--allow-empty", "-m", f"feat({task_id}): verified agent implementation"
        )
        return git(path, "rev-parse", "HEAD")

    def merge(self, commit: str) -> str:
        try:
            git(self.integration, "merge", "--no-ff", "--no-edit", commit)
        except GitError:
            try:
                git(self.integration, "merge", "--abort")
            except GitError:
                pass
            raise
        return git(self.integration, "rev-parse", "HEAD")

    def diff(self) -> str:
        return git(self.integration, "diff", self.revision, "HEAD", "--")
