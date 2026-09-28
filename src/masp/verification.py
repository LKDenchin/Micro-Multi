"""Tool adapters: safe fixture interpreter and fail-closed Docker execution."""

import ast
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from masp.domain import Check, CheckResult, Finding, Proposal, TaskSpec
from masp.workspace import allowed, git, target


class ToolAdapter(Protocol):
    def execute(self, root: Path, check: Check, stop: Callable[[], bool]) -> CheckResult: ...


def contract_review(task: TaskSpec, proposal: Proposal) -> list[Finding]:
    findings = []
    for name, content in proposal.files.items():
        message = ""
        if not allowed(name, task.allowed_paths):
            message = "File is outside the registered task scope"
        elif name.endswith(".py"):
            try:
                ast.parse(content, filename=name)
            except SyntaxError as error:
                message = str(error)
        if message:
            findings.append(
                Finding(
                    severity="HIGH",
                    category="contract",
                    file=name,
                    message=message,
                    evidence=message,
                    suggested_fix="Follow declared scope and valid Python syntax",
                    blocking=True,
                )
            )
    return findings


class FixtureTool:
    """Evaluates only a two-argument arithmetic AST; never exec/eval/import generated code."""

    def _function(self, path: Path, name: str, a: int, b: int) -> int:
        tree = ast.parse(path.read_text("utf-8"))
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
            raise ValueError("Fixture supports one arithmetic function per module")
        fn = tree.body[0]
        if fn.name != name or len(fn.body) != 1 or not isinstance(fn.body[0], ast.Return):
            raise ValueError("Unexpected fixture function")
        expr = fn.body[0].value
        if (
            [arg.arg for arg in fn.args.args] != ["a", "b"]
            or not isinstance(expr, ast.BinOp)
            or not isinstance(expr.left, ast.Name)
            or not isinstance(expr.right, ast.Name)
            or expr.left.id != "a"
            or expr.right.id != "b"
        ):
            raise ValueError("Only return a + b / a - b is accepted")
        if isinstance(expr.op, ast.Add):
            return a + b
        if isinstance(expr.op, ast.Sub):
            return a - b
        raise ValueError("Unsupported arithmetic operator")

    def execute(self, root: Path, check: Check, stop: Callable[[], bool]) -> CheckResult:
        started = time.monotonic()
        error = ""
        try:
            if stop():
                return CheckResult(
                    name=check.name,
                    layer=check.layer,
                    status="cancelled",
                    command=check.command,
                    exit_code=None,
                    duration_ms=0,
                )
            if check.command not in [
                ["fixture", name] for name in ("compile", "add", "subtract", "all")
            ]:
                raise ValueError("Fixture refuses arbitrary commands")
            operation = check.command[1]
            if operation == "compile":
                for path in root.rglob("*.py"):
                    target(root, path.relative_to(root).as_posix())
                    compile(path.read_text("utf-8"), str(path), "exec")
            else:
                for name in ("add", "subtract") if operation == "all" else (operation,):
                    for a, b in ((3, 2), (-4, 7), (0, 0), (0, -2)):
                        expected = a + b if name == "add" else a - b
                        actual = self._function(target(root, f"calculator/{name}.py"), name, a, b)
                        if actual != expected:
                            raise AssertionError(
                                f"{name}({a},{b}): expected {expected}, got {actual}"
                            )
        except (ValueError, SyntaxError, OSError, AssertionError) as exc:
            error = str(exc)
        return CheckResult(
            name=check.name,
            layer=check.layer,
            status="failed" if error else "passed",
            command=check.command,
            exit_code=1 if error else 0,
            duration_ms=int((time.monotonic() - started) * 1000),
            stdout="" if error else "All declared fixture checks passed",
            stderr=error,
            error_type="TEST_ERROR" if error else None,
        )


class DockerTool:
    """Only a disposable, read-only copy of project files is mounted into the sandbox."""

    def __init__(self, image: str | None = None):
        self.image = image or os.environ.get("MASP_SANDBOX_IMAGE", "python:3.12-slim")

    def command(self, snapshot: Path, name: str, check: Check) -> list[str]:
        return [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=128",
            "--memory=512m",
            "--memory-swap=512m",
            "--cpus=1",
            "--user=65534:65534",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
            "-e",
            "PYTHONPYCACHEPREFIX=/tmp/pycache",
            "--mount",
            f"type=bind,source={snapshot},target=/workspace,readonly",
            "--workdir=/workspace",
            self.image,
            *check.command,
        ]

    def execute(self, root: Path, check: Check, stop: Callable[[], bool]) -> CheckResult:
        started = time.monotonic()
        base: dict[str, Any] = {"name": check.name, "layer": check.layer, "command": check.command}
        if not shutil.which("docker"):
            return CheckResult(
                **base,
                status="failed",
                exit_code=None,
                duration_ms=0,
                stderr="Docker unavailable; host execution is forbidden",
                error_type="SECURITY_BLOCK",
            )
        name = "masp-" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="masp-sandbox-") as temporary:
            snapshot = Path(temporary) / "workspace"
            snapshot.mkdir()
            names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
            total = 0
            entries = sorted(set(names.split("\0")) - {""})
            if len(entries) > 2000:
                raise ValueError("RESOURCE_ERROR: too many workspace files")
            for relative in entries:
                source = target(root, relative)
                if not source.is_file():
                    continue
                total += source.stat().st_size
                if total > 20_000_000:
                    raise ValueError("RESOURCE_ERROR: workspace exceeds 20 MB")
                destination = target(snapshot, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            args = self.command(snapshot, name, check)
            error_type = None
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                process = subprocess.Popen(args, stdout=stdout, stderr=stderr)
                try:
                    while process.poll() is None:
                        oversized = (
                            max(
                                os.fstat(stdout.fileno()).st_size, os.fstat(stderr.fileno()).st_size
                            )
                            > 2_000_000
                        )
                        if stop() or time.monotonic() - started > check.timeout or oversized:
                            error_type = (
                                "CANCELLED"
                                if stop()
                                else ("RESOURCE_ERROR" if oversized else "TIMEOUT")
                            )
                            subprocess.run(
                                ["docker", "rm", "-f", name],
                                capture_output=True,
                                timeout=10,
                                check=False,
                            )
                            process.kill()
                            break
                        time.sleep(0.05)
                    process.wait(timeout=10)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
                stdout.seek(0)
                stderr.seek(0)
                out = stdout.read(65536).decode("utf-8", errors="replace")
                err = stderr.read(65536).decode("utf-8", errors="replace")
            if process.returncode and not error_type:
                error_type = "BUILD_ERROR" if check.layer == "build" else "TEST_ERROR"
            return CheckResult(
                **base,
                status="cancelled"
                if error_type == "CANCELLED"
                else ("failed" if error_type else "passed"),
                exit_code=process.returncode,
                duration_ms=int((time.monotonic() - started) * 1000),
                stdout=out,
                stderr=err,
                error_type=error_type,
            )
