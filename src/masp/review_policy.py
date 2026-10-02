"""Choose independent review without repeating it for every routine artifact."""

import re
from collections.abc import Mapping

_CRITICAL_PATH = re.compile(
    r"(?:^|[/_.-])(?:auth|authorization|permission|permissions|security|secret|secrets|"
    r"credential|credentials|migration|migrations|storage|persistence|session|sessions|"
    r"supervisor|scheduler|concurrency|lock|locks|native|protocol|contract|contracts|"
    r"api|router|routes|schema|schemas)(?:[/_.-]|$)",
    re.IGNORECASE,
)
_CRITICAL_CODE = re.compile(
    r"\b(?:eval|exec)\s*\(|\b(?:pickle\.loads|shell\s*=\s*True|"
    r"asyncio\.(?:Lock|Semaphore|gather|create_task|TaskGroup)|threading\.(?:Lock|RLock|Thread)|"
    r"BEGIN\s+TRANSACTION|ALTER\s+TABLE|DROP\s+TABLE)\b",
    re.IGNORECASE,
)


def review_reasons(files: Mapping[str, str]) -> list[str]:
    """Conservative triggers; syntax, scope and required tests remain unconditional."""
    reasons = []
    for path, content in files.items():
        normalized = path.replace("\\", "/")
        if _CRITICAL_PATH.search(normalized) or _CRITICAL_CODE.search(content):
            reasons.append(path)
        elif normalized.rsplit("/", 1)[-1] in {
            "package.json",
            "pyproject.toml",
            "Dockerfile",
            "cordis.yml",
            "cordis.patch.yml",
        } or normalized.startswith(".github/workflows/"):
            reasons.append(path)
    return sorted(reasons)
