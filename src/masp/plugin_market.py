"""Read the upstream dsh-market catalog; install through the existing host transaction."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx

CATALOG_URL = "https://awesome-dsh-plugin.com/plugins.json"
_lock = threading.Lock()
_catalog: dict[str, Any] = {}
_fetched = 0.0


def catalog(
    query: str = "", offset: int = 0, limit: int = 40, category: str = "", sort: str = "stars"
) -> dict[str, Any]:
    global _catalog, _fetched
    with _lock:
        if not _catalog or time.monotonic() - _fetched > 300:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                with client.stream("GET", CATALOG_URL) as response:
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 32 * 1024 * 1024:
                            raise ValueError("插件目录超过 32 MB")
                        chunks.append(chunk)
            data = json.loads(b"".join(chunks))
            if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
                raise ValueError("插件市场返回了无效目录")
            _catalog, _fetched = data, time.monotonic()
        entries = [item for item in _catalog["plugins"] if isinstance(item, dict)]
        search = query.casefold().strip()
        if search:
            entries = [
                item
                for item in entries
                if search in json.dumps(item, ensure_ascii=False).casefold()
            ]
        if category:
            entries = [
                item
                for item in entries
                if category
                in (
                    item.get("category", [])
                    if isinstance(item.get("category"), list)
                    else [item.get("category")]
                )
            ]
        if sort == "name":
            entries.sort(key=lambda item: str(item.get("name", "")).casefold())
        else:
            key = "downloads" if sort == "downloads" else "stars"
            entries.sort(key=lambda item: int(item.get(key) or 0), reverse=True)
        return {
            "source": CATALOG_URL,
            "updated": _catalog.get("updated"),
            "total": len(entries),
            "categories": _catalog.get("categories", {}),
            "plugins": entries[offset : offset + limit],
        }


def install_source(name: str) -> str:
    entries = catalog(limit=100000)["plugins"]
    entry = next((item for item in entries if item.get("name") == name), None)
    if not entry:
        raise ValueError("插件已不在市场目录中，请刷新")
    if entry.get("npm"):
        return (
            "npm:"
            + str(entry["npm"])
            + ("@" + str(entry["version"]) if entry.get("version") else "")
        )
    url = str(entry.get("url") or "")
    if not url.startswith("https://github.com/"):
        raise ValueError("市场插件来源无效")
    repo, _, subpath = url.partition("#")
    return repo.removesuffix(".git") + ".git" + ("#" + subpath if subpath else "")
