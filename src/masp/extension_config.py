"""Edit the configuration that is actually used by installed Host plugins."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from masp.cordis_runtime import close_native_hosts, inspect_native
from masp.plugin_surface import surface_host
from masp.storage import Store, now

_lock = threading.RLock()


def bundle_configuration(
    store: Store,
    home: Path,
    plugin_id: str,
    entries: list[dict[str, Any]] | None = None,
    revision: str | None = None,
) -> dict[str, Any]:
    with _lock:
        bundle = store.get("dsh_bundle", plugin_id)
        manifest = bundle.get("native_manifest")
        if not manifest or not manifest.get("plugins"):
            return {"entries": [], "editable": False, "message": "此扩展没有 Host 参数。"}
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        worker = surface_host(store, home, plugin_id)
        current = worker.request("bundle-config", plugins=manifest["plugins"], pluginId=plugin_id)[
            "entries"
        ]
        if entries is None:
            return {"entries": current, "editable": True, "revision": digest}
        if revision != digest:
            raise ValueError("插件配置已变化，请重新打开配置页")
        keys = [entry["key"] for entry in current]
        if [entry.get("key") for entry in entries] != keys:
            raise ValueError("只能修改当前插件的参数，不能替换入口")
        candidate = copy.deepcopy(manifest)
        for entry in entries:
            config = entry.get("config")
            if not isinstance(config, dict):
                raise ValueError("每项 config 必须为 JSON 对象")
            index, _, patch_id = entry["key"].partition(":")
            item = candidate["plugins"][int(index)]
            if patch_id:
                item.setdefault("configOverrides", {})[patch_id] = config
            else:
                item["config"] = config
        inventory = inspect_native(home, candidate, store, plugin_id)
        tool_names = {tool["name"] for tool in inventory["tools"]}
        registered = [item for item in store.list("plugin") if item.get("bundle_id") == plugin_id]
        if {
            item.get("native_tool")
            for item in registered
            if item.get("runtime") == "native-cordis-host"
        } != tool_names:
            raise ValueError("参数会改变工具目录，请重新安装插件后再修改")
        records = [
            ("dsh_bundle", {**bundle, "native_manifest": candidate, "updated_at": now()}, "")
        ]
        records.extend(
            ("plugin", {**item, "native_manifest": candidate, "updated_at": now()}, "")
            for item in registered
            if item.get("runtime") == "native-cordis-host"
        )
        close_native_hosts(store, plugin_id)
        store.apply_batch(records, [])
        return {"saved": True}
