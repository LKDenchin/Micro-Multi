"""Build a relocatable Windows/Linux Python runtime with locked production dependencies."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.14.7"
LINUX_VERSION = "3.14.8"
LINUX_ARCHIVE = "cpython-3.14.8+20261001-x86_64-unknown-linux-gnu-install_only.tar.gz"
LINUX_SHA256 = "813c89e2589fed92333e18bde230a43280962e6f24bb0b861dc8ce532cfd6567"


def prepare_linux() -> None:
    import platform

    if platform.machine() not in {"x86_64", "AMD64"}:
        raise SystemExit("Linux desktop builds currently target x64.")
    target = ROOT / "build" / "desktop" / "python"
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / LINUX_ARCHIVE
    url = (
        "https://github.com/astral-sh/python-build-standalone/releases/download/20261001/"
        + LINUX_ARCHIVE
    )
    if not archive.exists():
        urllib.request.urlretrieve(url, archive)
    digest = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
    if digest != LINUX_SHA256:
        raise SystemExit("Standalone Python archive checksum mismatch")
    with tarfile.open(archive) as source:
        source.extractall(target.parent, filter="data")
    executable = target / "bin" / "python3"
    subprocess.run(
        [
            str(executable),
            "-m",
            "pip",
            "install",
            "--only-binary=:all:",
            "-r",
            str(ROOT / "requirements-desktop.lock"),
        ],
        check=True,
    )
    # Relocatable CPython preserves a real executable for built-in MCP and project tools.
    (target.parent / "runtime-manifest.json").write_text(
        json.dumps(
            {
                "python": LINUX_VERSION,
                "platform": "linux-x64",
                "source": url,
                "archive_sha256": digest,
                "requirements_sha256": hashlib.sha256(
                    (ROOT / "requirements-desktop.lock").read_bytes()
                ).hexdigest(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [str(executable), "-c", "import fastapi, uvicorn, keyring, mcp, httpx2, jsonschema"],
        check=True,
    )
    print(f"Prepared Linux Python runtime: {target}")


def main() -> None:
    if sys.platform == "linux":
        prepare_linux()
        return
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise SystemExit("Desktop packaging currently supports Windows x64 only.")
    target = ROOT / "build" / "desktop" / "python"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    archive = target.parent / f"python-{VERSION}-embed-amd64.zip"
    url = f"https://www.python.org/ftp/python/{VERSION}/{archive.name}"
    if not archive.exists():
        urllib.request.urlretrieve(url, archive)
    with zipfile.ZipFile(archive) as source:
        source.extractall(target)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--only-binary=:all:",
            "--target",
            str(target / "Lib" / "site-packages"),
            "-r",
            str(ROOT / "requirements-desktop.lock"),
        ],
        check=True,
    )
    (target / "python314._pth").write_text(
        "python314.zip\n.\nLib/site-packages\n../app/src\nimport site\n", encoding="utf-8"
    )
    # Node's module resolution and the review CLI expect src/ next to node_modules/.
    metadata = {
        "python": VERSION,
        "platform": "win32-x64",
        "source": url,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "requirements_sha256": hashlib.sha256(
            (ROOT / "requirements-desktop.lock").read_bytes()
        ).hexdigest(),
    }
    (target.parent / "runtime-manifest.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    subprocess.run(
        [
            str(target / "python.exe"),
            "-c",
            "import fastapi, uvicorn, keyring, mcp, httpx2, jsonschema",
        ],
        check=True,
    )
    print(f"Prepared Windows Python runtime: {target}")


if __name__ == "__main__":
    main()
