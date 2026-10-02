"""Acquire npm/git bundles into app-owned sources; registration remains transactional."""

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def remote_source(source: str) -> bool:
    return source.startswith(("npm:", "git+https://")) or (
        source.startswith("https://") and source.endswith(".git")
    )


def package_manager(root: Path) -> tuple[str, str]:
    package = json.loads((root / "package.json").read_text("utf-8"))
    declared = str(package.get("packageManager", ""))
    name = "pnpm" if declared.startswith("pnpm@") or (root / "pnpm-lock.yaml").is_file() else "npm"
    executable = shutil.which(name + ".cmd" if os.name == "nt" else name)
    if not executable:
        raise ValueError(f"{name} is required by this bundle; dependency scripts were not executed")
    return name, executable


def acquire_bundle(home: Path, source: str) -> tuple[Path, Path]:
    base = (home / "extension-sources").resolve()
    base.mkdir(parents=True, exist_ok=True)
    stage = base / uuid.uuid4().hex
    stage.mkdir()

    def run(argv: list[str], cwd: Path) -> None:
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode:
            raise ValueError(
                "Bundle acquisition failed: " + (result.stderr or result.stdout)[-2000:]
            )

    try:
        if source.startswith("npm:"):
            spec = source[4:]
            match = re.fullmatch(
                r"(@[a-z0-9_.-]+/[a-z0-9_.-]+|[a-z0-9_.-]+)(?:@([a-zA-Z0-9_.+~-]+))?", spec
            )
            if not match:
                raise ValueError("Use npm:package@version or npm:@scope/package@version")
            npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
            if not npm:
                raise ValueError("npm is required to acquire this bundle")
            (stage / "package.json").write_text('{"private":true}', encoding="utf-8")
            run(
                [
                    npm,
                    "install",
                    "--ignore-scripts",
                    "--no-audit",
                    "--no-fund",
                    "--save-exact",
                    spec,
                ],
                stage,
            )
            root = stage / "node_modules" / match[1]
        else:
            url = source.removeprefix("git+")
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "Git bundle requires an HTTPS repository URL without embedded credentials"
                )
            git = shutil.which("git")
            if not git:
                raise ValueError("git is required to acquire this bundle")
            root = stage / "repository"
            run([git, "clone", "--depth", "1", "--", url, str(root)], stage)
            if (root / "package.json").is_file():
                manager, executable = package_manager(root)
                if manager == "pnpm":
                    run(
                        [
                            executable,
                            "install",
                            "--ignore-scripts",
                            "--frozen-lockfile"
                            if (root / "pnpm-lock.yaml").is_file()
                            else "--no-frozen-lockfile",
                        ],
                        root,
                    )
                else:
                    command = "ci" if (root / "package-lock.json").is_file() else "install"
                    run([executable, command, "--ignore-scripts", "--no-audit", "--no-fund"], root)
        if not root.is_dir():
            raise ValueError("Acquired bundle has no package directory")
        return root, stage
    except Exception:
        discard_source(home, stage)
        raise


def discard_source(home: Path, stage: Path) -> None:
    base = (home / "extension-sources").resolve()
    resolved = stage.resolve()
    if resolved.parent != base or not re.fullmatch(r"[0-9a-f]{32}", resolved.name):
        raise ValueError("Refusing to remove a path outside managed bundle sources")
    shutil.rmtree(resolved)
