"""Open Code Review bridge for staged changes in an isolated task workspace."""

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from masp.domain import Finding
from masp.model_settings import ModelConfig


def find_ocr_binary() -> Path:
    configured = os.environ.get("MASP_OCR_BINARY")
    if configured:
        path = Path(configured).resolve()
        if path.is_file():
            return path
        raise ValueError("Configured review binary does not point to a file")
    system = {"Windows": "win32", "Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    architecture = {"AMD64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(
        platform.machine()
    )
    if system and architecture:
        binary = "opencodereview.exe" if system == "win32" else "opencodereview"
        path = (
            Path(__file__).resolve().parents[2]
            / "node_modules"
            / "@alibaba-group"
            / f"ocr-{system}-{architecture}"
            / "bin"
            / binary
        )
        if path.is_file():
            return path
    external = shutil.which("ocr")
    if external:
        return Path(external)
    raise ValueError(
        "Open Code Review is unavailable; run npm install in the Micro-Multi directory"
    )


def ocr_engine_status() -> dict[str, Any]:
    """Return real installation status of https://github.com/alibaba/open-code-review."""
    try:
        binary_path = find_ocr_binary()
        return {
            "loaded": True,
            "engine": "open-code-review",
            "package": "@alibaba-group/open-code-review",
            "repository": "https://github.com/alibaba/open-code-review",
            "binary": str(binary_path),
        }
    except ValueError as err:
        return {
            "loaded": False,
            "engine": "open-code-review",
            "package": "@alibaba-group/open-code-review",
            "repository": "https://github.com/alibaba/open-code-review",
            "error": str(err),
        }


def run_open_code_review(
    workspace: Path, config: ModelConfig, *, timeout: int = 600
) -> tuple[list[Finding], dict[str, Any]]:
    """Review only staged task changes; keep credentials out of logs and records."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
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
    env.update(
        OCR_LLM_URL=config.base_url.rstrip("/") + "/chat/completions",
        OCR_LLM_TOKEN=config.api_key,
        OCR_LLM_MODEL=config.model,
        OCR_LLM_PROTOCOL="openai",
        OCR_USE_ANTHROPIC="false",
        OCR_NO_UPDATE="1",
        GIT_TERMINAL_PROMPT="0",
    )
    try:
        result = subprocess.run(
            [str(find_ocr_binary()), "review", "--format", "json", "--audience", "agent"],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Open Code Review could not finish: {type(error).__name__}") from None
    if result.returncode:
        raise RuntimeError(f"Open Code Review exited with code {result.returncode}")
    try:
        report = json.loads(result.stdout)
        if report["status"] not in {"success", "skipped"}:
            raise ValueError("review is incomplete")
        comments = report["comments"]
        if not isinstance(comments, list):
            raise ValueError("comments must be a list")
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError(f"Open Code Review returned invalid results: {error}") from None
    findings = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        raw_severity = str(comment.get("severity", "medium")).upper()
        severity = (
            raw_severity
            if raw_severity in {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
            else "MEDIUM"
        )
        path = str(comment.get("path") or "")
        line = comment.get("start_line")
        findings.append(
            Finding.model_validate(
                {
                    "severity": severity,
                    "category": str(comment.get("category") or "code-review"),
                    "file": path,
                    "line": line if isinstance(line, int) and line > 0 else None,
                    "message": str(comment.get("content") or "Review finding"),
                    "evidence": str(comment.get("existing_code") or ""),
                    "suggested_fix": str(comment.get("suggestion_code") or ""),
                    "blocking": severity in {"HIGH", "CRITICAL"},
                }
            )
        )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return findings, {
        "engine": "open-code-review",
        "status": report["status"],
        "model": config.model,
        "files_reviewed": summary.get("files_reviewed"),
        "comments": len(findings),
        "session_id": report.get("session_id"),
    }
