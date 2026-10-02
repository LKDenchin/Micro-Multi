"""Native Cordis Loader configurations and patch layers, validated by Harness boot."""

import hashlib
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from masp.cordis_runtime import CordisWorker, composed_manifest
from masp.storage import Store, now

_guard = threading.RLock()


def profile_form(
    store: Store,
    home: Path,
    name: str,
    entries: list[dict[str, Any]] | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Use the upstream schema exporter and the same validated save transaction."""
    directory = profile_directory(home, name)
    config_path, patch_path = directory / "cordis.yml", directory / "cordis.patch.yml"
    if not config_path.is_file() or config_path.is_symlink() or patch_path.is_symlink():
        raise ValueError("Profile is missing or contains symlinked configuration")
    with _guard:
        revision = hashlib.sha256(
            config_path.read_bytes() + (patch_path.read_bytes() if patch_path.exists() else b"")
        ).hexdigest()
        if expected_revision is not None and expected_revision != revision:
            raise ValueError("Profile changed since the form was loaded; reload before saving")
        manifest = composed_manifest(store)
        manifest["profile"] = {
            "configPath": str(config_path),
            "patchPaths": [str(patch_path)] if patch_path.is_file() else [],
        }
        worker = CordisWorker(home, manifest, directory)
        try:
            if entries is None:
                return {**worker.request("profile-schema"), "revision": revision}
            result = worker.request("profile-form-patch", entries=entries)
        finally:
            worker.close()
        return save_profile(store, home, name, config_path.read_text("utf-8"), result["patch"])


def profile_directory(home: Path, name: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}", name):
        raise ValueError("Profile name must contain 1–48 letters, numbers, underscores or hyphens")
    base = home / "native-profiles"
    if base.is_symlink():
        raise ValueError("Profile directory must not be a symlink")
    base = base.resolve()
    path = base / name
    if path.is_symlink() or (base.exists() and base.is_symlink()):
        raise ValueError("Profile directory must not be a symlink")
    return path


def list_profiles(store: Store, home: Path) -> dict[str, Any]:
    try:
        active = store.get("native_profile", "active").get("name")
    except KeyError:
        active = None
    base = home / "native-profiles"
    profiles = []
    if base.is_dir():
        for directory in sorted(base.iterdir()):
            if directory.is_symlink() or not directory.is_dir():
                continue
            config = directory / "cordis.yml"
            patch = directory / "cordis.patch.yml"
            if config.is_file():
                profiles.append(
                    {
                        "name": directory.name,
                        "active": active == directory.name,
                        "config": config.read_text("utf-8"),
                        "patch": patch.read_text("utf-8") if patch.is_file() else "[]\n",
                    }
                )
    return {"active": active, "profiles": profiles}


def save_profile(
    store: Store, home: Path, name: str, config: str, patch: str, activate: bool = True
) -> dict[str, Any]:
    if len(config.encode("utf-8")) > 256_000 or len(patch.encode("utf-8")) > 256_000:
        raise ValueError("Native profile config and patch each support up to 256 KB")
    directory = profile_directory(home, name)
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / "cordis.yml"
    patch_path = directory / "cordis.patch.yml"
    candidates = [directory / (uuid.uuid4().hex + suffix) for suffix in (".yml", ".patch.yml")]
    bundle_id = "native-profile-" + name
    with _guard:
        if any(path.is_symlink() for path in (config_path, patch_path)):
            raise ValueError("Profile files must not be symlinks")
        previous = [
            path.read_bytes() if path.exists() else None for path in (config_path, patch_path)
        ]
        try:
            for path, text in zip(candidates, (config, patch), strict=True):
                path.write_text(text, encoding="utf-8")
            manifest = composed_manifest(store)
            manifest["profile"] = {
                "configPath": str(candidates[0]),
                "patchPaths": [str(candidates[1])],
            }
            worker = CordisWorker(home, manifest, directory)
            try:
                inventory = worker.inventory
                inactive = [
                    entry
                    for entry in inventory.get("profileEntries", [])
                    if entry["state"] == "inactive"
                ]
                if inactive:
                    raise ValueError(
                        "Native profile entries did not activate: "
                        + ", ".join(entry["name"] for entry in inactive)
                    )
            finally:
                worker.close()
            existing_names = {
                tool.get("native_tool")
                for tool in store.list("plugin")
                if tool.get("runtime") == "native-cordis-host"
                and tool.get("bundle_id") != bundle_id
                and not str(tool.get("bundle_id", "")).startswith("native-profile-")
            }
            tools = [tool for tool in inventory["tools"] if tool["name"] not in existing_names]
            active_name = list_profiles(store, home)["active"]
            activate = activate or active_name == name
            for candidate, target in zip(candidates, (config_path, patch_path), strict=True):
                os.replace(candidate, target)
            if activate:
                records: list[tuple[str, dict[str, Any], str]] = [
                    (
                        "native_profile",
                        {
                            "id": "active",
                            "name": name,
                            "configPath": str(config_path),
                            "patchPaths": [str(patch_path)],
                            "layerPaths": [
                                path
                                for layer in inventory.get("configLayers", [])
                                if layer["label"].startswith("bundle:")
                                for path in layer["paths"]
                            ],
                            "updated_at": now(),
                        },
                        "",
                    )
                ]
                for item in store.list("dsh_bundle"):
                    if item.get("kind") == "native-profile" and item["id"] != bundle_id:
                        records.append(("dsh_bundle", {**item, "enabled": False}, ""))
                records.append(
                    (
                        "dsh_bundle",
                        {
                            "id": bundle_id,
                            "name": "Native profile · " + name,
                            "kind": "native-profile",
                            "profile_name": name,
                            "source_path": str(directory),
                            "enabled": True,
                            "runtime": "native-cordis-host",
                            "native_manifest": {"root": str(directory), "plugins": []},
                            "native_versions": inventory["versions"],
                            "components": [],
                            "updated_at": now(),
                        },
                        "",
                    )
                )
                for tool in tools:
                    record_id = (
                        "plugin-"
                        + hashlib.sha256((bundle_id + ":" + tool["name"]).encode()).hexdigest()[:16]
                    )
                    records.append(
                        (
                            "plugin",
                            {
                                **tool,
                                "id": record_id,
                                "enabled": True,
                                "runtime": "native-cordis-host",
                                "native_tool": tool["name"],
                                "bundle_id": bundle_id,
                            },
                            "",
                        )
                    )
                new_names = {tool["name"] for tool in tools}
                deletes = [
                    ("plugin", item["id"])
                    for item in store.list("plugin")
                    if item.get("bundle_id") == bundle_id
                    and item.get("native_tool") not in new_names
                ]
                store.apply_batch(records, deletes)
            return {"name": name, "active": activate, "tool_count": len(tools)}
        except Exception:
            for path, content in zip((config_path, patch_path), previous, strict=True):
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
            raise
        finally:
            for path in candidates:
                path.unlink(missing_ok=True)
