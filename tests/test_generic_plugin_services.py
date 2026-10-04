"""Real service activation without plugin-specific compatibility adapters."""

import json

import pytest

from masp.cordis_runtime import CordisWorker, native_manifest


def test_new_plugin_resolves_framework_services_and_settings(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "package.json").write_text(
        json.dumps(
            {
                "name": "unseen-generic-plugin",
                "type": "module",
                "main": "index.mjs",
                "dependencies": {"@deepseek-ai/cordis": "~4.0.4"},
            }
        )
    )
    (package / "index.mjs").write_text("""
import Schema from '@deepseek-ai/schemastery';
import {defineTool} from '@deepseek-ai/dsh-tools';
export const name='unseen-generic-plugin';
export const inject=['sessionQuery','workspaceRegistry','timer','storage','tools'];
export const Config=Schema.object({enabled:Schema.boolean().default(true),failOnStart:Schema.boolean().default(false)});
export function apply(ctx,config){if(config.failOnStart)throw Error('deliberate startup failure');ctx.tools.register(defineTool({name:'generic_probe',description:'Probe real services',parameters:{},output:{schema:{type:'object',additionalProperties:false,properties:{enabled:{type:'boolean',required:true},backend:{type:'boolean',required:true}}},render:(_,value)=>[{type:'text',text:JSON.stringify(value)}]},async execute(){return {enabled:config.enabled,backend:!!ctx.storage.backend.get('json')};}}));}
""")
    manifest = native_manifest(package)
    manifest["plugins"][0]["bundleId"] = "generic"
    worker = CordisWorker(tmp_path / "home", manifest, package)
    try:
        result = worker.request("call", name="generic_probe", arguments={})
        assert result["value"]["backend"] is True
        assert result["value"]["enabled"] is True
        capabilities = worker.request("plugin-capabilities", pluginId="generic")
        assert capabilities["settingsNamespaces"] == ["unseen-generic-plugin"]
        assert all(plugin["state"] == "active" for plugin in worker.inventory["plugins"])
        described = worker.request(
            "plugin-rpc", channel="/api", method="settings/describe", payload={"args": {}}
        )["result"]
        assert described["ok"]
        descriptor = next(
            row for row in described["value"]["namespaces"] if row["ns"] == "unseen-generic-plugin"
        )
        saved = worker.request(
            "plugin-rpc",
            channel="/api",
            method="settings/update",
            payload={
                "args": {
                    "ns": descriptor["ns"],
                    "patch": {"enabled": False},
                    "expectedRevision": descriptor["revision"],
                }
            },
        )["result"]
        assert saved["ok"], saved
        assert (
            worker.request("call", name="generic_probe", arguments={})["value"]["enabled"] is False
        )
        rejected = worker.request(
            "plugin-rpc",
            channel="/api",
            method="settings/update",
            payload={"args": {"ns": descriptor["ns"], "patch": {"failOnStart": True}}},
        )["result"]
        assert not rejected["ok"]
        assert (
            worker.request("call", name="generic_probe", arguments={})["value"]["enabled"] is False
        )
        persisted = json.loads((tmp_path / "home/native-bundle-settings.json").read_text())
        assert persisted["generic"]["unseen-generic-plugin"].get("failOnStart", False) is False
        (package / "bad.mjs").write_text(
            "export const name='bad-provider'; export const inject=['unavailable_test_service']; export function apply(){}"
        )
        with pytest.raises(ValueError, match="No installed provider"):
            worker.request(
                "sync",
                plugins=[*manifest["plugins"], {"entry": "bad.mjs", "bundleId": "bad"}],
                skillRoots=[],
            )
        worker.request("sync", plugins=manifest["plugins"], skillRoots=[])
        assert (
            worker.request("call", name="generic_probe", arguments={})["value"]["enabled"] is False
        )
        assert worker.request("plugin-capabilities", pluginId="bad")["settingsNamespaces"] == []
    finally:
        worker.close()

    worker = CordisWorker(tmp_path / "home", manifest, package)
    try:
        assert (
            worker.request("call", name="generic_probe", arguments={})["value"]["enabled"] is False
        )
    finally:
        worker.close()


def test_host_provisions_library_declared_only_for_development(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "package.json").write_text(
        json.dumps(
            {
                "name": "unseen-host-library",
                "version": "1.0.0",
                "type": "module",
                "exports": {".": "./index.js"},
            }
        ),
        encoding="utf-8",
    )
    (library / "index.js").write_text("export const answer=42;", encoding="utf-8")
    package = tmp_path / "package"
    package.mkdir()
    (package / "package.json").write_text(
        json.dumps(
            {
                "name": "host-library-fixture",
                "type": "module",
                "main": "index.mjs",
                "microMulti": {"cordis": {"entry": "index.mjs"}},
                "devDependencies": {"unseen-host-library": "file:" + str(library)},
            }
        ),
        encoding="utf-8",
    )
    (package / "index.mjs").write_text(
        "import {answer} from 'unseen-host-library'; export const inject=['connection']; export function apply(ctx){ctx.connection.rpc.handle('/library-probe',()=>({answer}));}",
        encoding="utf-8",
    )
    manifest = native_manifest(package)
    worker = CordisWorker(tmp_path / "home", manifest, package)
    try:
        assert worker.request("plugin-rpc", channel="/library-probe", method="read", payload={})[
            "result"
        ] == {"answer": 42}
        assert (
            tmp_path / "home/native-dependencies/node_modules/unseen-host-library/package.json"
        ).is_file()
    finally:
        worker.close()
