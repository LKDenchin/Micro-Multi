"""Check Git publication candidates without exposing matched secret values."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {".masp", "evidence", ".research", ".venv", "node_modules", "dist", "build"}
PATTERNS = {
    "API token": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential URL": re.compile(rb"https?://[^\s/:]+:[^\s/@]+@"),
}


def main() -> None:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    issues: list[str] = []
    count = 0
    for name in sorted(set(result.stdout.decode("utf-8").split("\0")) - {""}):
        path = ROOT / name
        if not path.is_file():
            continue
        if FORBIDDEN.intersection(Path(name).parts) or name.startswith("docs/screenshots/"):
            issues.append(f"Generated/private path: {name}")
        if path.name.startswith(".env") and path.name != ".env.example":
            issues.append(f"Environment file: {name}")
        payload = path.read_bytes()
        for label, pattern in PATTERNS.items():
            # Reserved example.com credentials explicitly exercise rejection, not authentication.
            matches = pattern.findall(payload)
            if name == "tests/test_extension_sources.py" and label == "credential URL":
                matches = [value for value in matches if value != b"https://" + b"name:secret@"]
            if matches:
                issues.append(f"{label}: {name}")
        count += 1
    if issues:
        print("\n".join(issues))
        raise SystemExit(f"Publication audit failed: {len(issues)} finding(s)")
    print(
        f"Publication audit passed: {count} files; no known token/private-key patterns or runtime data"
    )


if __name__ == "__main__":
    main()
