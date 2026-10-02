import json

from masp.cordis_runtime import close_native_hosts
from masp.native_profiles import profile_form, save_profile
from masp.storage import Store


def test_bundle_home_profile_invocation_precedence_uses_upstream_patches(tmp_path, monkeypatch):
    home = tmp_path / "home"
    directory = home / "native-profiles" / "layers"
    bundle = directory / "node_modules" / "fixture-bundle"
    bundle.mkdir(parents=True)
    plugin = tmp_path / "layer-plugin.mjs"
    plugin.write_text("export const name='layer-fixture'; export function apply(ctx,config){};")
    (bundle / "package.json").write_text(
        json.dumps(
            {
                "name": "fixture-bundle",
                "version": "1.0.0",
                "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
            }
        )
    )
    (bundle / "cordis.patch.yml").write_text(
        json.dumps(
            [
                {
                    "insert": [
                        {
                            "id": "entry",
                            "name": plugin.as_uri(),
                            "config": {"value": "bundle", "bundle": True},
                        }
                    ]
                }
            ]
        )
    )
    (directory / "package.json").write_text(
        json.dumps({"private": True, "dsh": {"profile": {"bundles": ["fixture-bundle"]}}})
    )
    (home / "cordis.patch.yml").write_text(
        json.dumps([{"id": "entry", "config": {"value": "home", "home": True}}])
    )
    invocation = tmp_path / "invocation.yml"
    invocation.write_text(
        json.dumps([{"id": "entry", "config": {"value": "invocation", "invocation": True}}])
    )
    monkeypatch.setenv("MICRO_MULTI_NATIVE_PATCHES", json.dumps([str(invocation)]))
    store = Store(home / "store.sqlite3")
    try:
        save_profile(
            store,
            home,
            "layers",
            "[]",
            json.dumps([{"id": "entry", "config": {"value": "profile", "profile": True}}]),
        )
        form = profile_form(store, home, "layers")
        config = form["entries"][0]["config"]
        assert config["value"] == "invocation"
        # Upstream config replacement semantics apply; do not invent a deep merge.
        assert config == {"value": "invocation", "invocation": True}
    finally:
        close_native_hosts(store)
