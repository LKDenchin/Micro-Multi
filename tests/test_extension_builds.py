import json

import pytest

from masp.cordis_runtime import close_native_hosts
from masp.extension_builds import approve_build
from masp.plugin_tools import install_dsh_plugin_from_path
from masp.storage import Store


def source(home, failing=False):
    stage = home / "extension-sources" / ("a" * 32)
    root = stage / "repository"
    root.mkdir(parents=True)
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "build-fixture",
                "version": "1.0.0",
                "main": "built.mjs",
                "dependencies": {"@deepseek-ai/cordis": "4.0.4"},
                "scripts": {"build": "node build.cjs"},
            }
        )
    )
    script = "const fs=require('node:fs');fs.appendFileSync('executed.txt','once\\n');"
    script += (
        "process.exit(2);"
        if failing
        else "fs.writeFileSync('built.mjs',\"export const name='built-fixture';"
        'export function apply(ctx){};");'
    )
    (root / "build.cjs").write_text(script)
    return root, stage


def test_build_is_reviewable_and_executes_only_after_exact_single_use_approval(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    root, stage = source(home)
    monkeypatch.setattr("masp.plugin_tools.acquire_bundle", lambda *args: (root, stage))
    pending = install_dsh_plugin_from_path(store, home, "git+https://example.com/repository.git")
    assert pending["status"] == "build_required" and stage.exists()
    assert not (root / "executed.txt").exists() and not store.list("dsh_bundle")
    try:
        installed = approve_build(store, home, pending["id"], pending["revision"], True)
        assert installed["runtime"] == "native-cordis-host"
        assert (root / "executed.txt").read_text() == "once\n"
        assert store.get("extension_build", pending["id"])["status"] == "completed"
        with pytest.raises(ValueError, match="consumed"):
            approve_build(store, home, pending["id"], pending["revision"], True)
    finally:
        close_native_hosts(store)


def test_changed_source_is_rejected_and_rejection_cleans_only_owned_stage(tmp_path, monkeypatch):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    root, stage = source(home)
    monkeypatch.setattr("masp.plugin_tools.acquire_bundle", lambda *args: (root, stage))
    pending = install_dsh_plugin_from_path(store, home, "npm:fixture")
    (root / "build.cjs").write_text("throw Error('changed')")
    with pytest.raises(ValueError, match="Source changed"):
        approve_build(store, home, pending["id"], pending["revision"], True)
    assert not (root / "executed.txt").exists()
    assert (
        approve_build(store, home, pending["id"], pending["revision"], False)["status"]
        == "rejected"
    )
    assert not stage.exists() and store.path.exists()


def test_failed_build_is_not_replayed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    root, stage = source(home, failing=True)
    monkeypatch.setattr("masp.plugin_tools.acquire_bundle", lambda *args: (root, stage))
    pending = install_dsh_plugin_from_path(store, home, "npm:fixture")
    with pytest.raises(ValueError, match="build failed"):
        approve_build(store, home, pending["id"], pending["revision"], True)
    with pytest.raises(ValueError, match="consumed"):
        approve_build(store, home, pending["id"], pending["revision"], True)
    assert (root / "executed.txt").read_text() == "once\n"


def test_published_package_build_installs_local_dev_tools_in_production_environment(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    root, stage = source(home)
    tool = stage / "build-tool"
    tool.mkdir()
    (tool / "package.json").write_text(
        json.dumps(
            {
                "name": "fixture-build-tool",
                "version": "1.0.0",
                "bin": {"fixture-build-tool": "cli.cjs"},
            }
        )
    )
    (tool / "cli.cjs").write_text("#!/usr/bin/env node\n" + (root / "build.cjs").read_text())
    package = json.loads((root / "package.json").read_text())
    package["dependencies"] = {}
    package["microMulti"] = {"cordis": {"entry": "built.mjs"}}
    package["devDependencies"] = {"fixture-build-tool": "file:" + tool.as_posix()}
    package["scripts"]["build"] = "fixture-build-tool"
    (root / "package.json").write_text(json.dumps(package))
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setenv("npm_config_omit", "dev")
    monkeypatch.setenv("npm_config_production", "true")
    monkeypatch.setattr("masp.plugin_tools.acquire_bundle", lambda *args: (root, stage))
    pending = install_dsh_plugin_from_path(store, home, "npm:fixture")
    assert pending["commands"][0]["argv"][1] == "install"
    assert not (root / "node_modules").exists()
    try:
        installed = approve_build(store, home, pending["id"], pending["revision"], True)
        assert installed["runtime"] == "native-cordis-host"
        assert (root / "executed.txt").read_text() == "once\n"
    finally:
        close_native_hosts(store)


def test_runtime_failure_in_published_artifacts_does_not_request_rebuild(tmp_path):
    from masp.extension_builds import prepare_build

    home = tmp_path / "home"
    root, stage = source(home)
    (root / "built.mjs").write_text("export function apply(){throw Error('runtime failure')}")
    store = Store(home / "store.sqlite3")
    assert prepare_build(store, home, root, stage, "npm:fixture", "runtime failure") is None
    assert not store.list("extension_build")
