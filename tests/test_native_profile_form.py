import json

import pytest

from masp.cordis_runtime import close_native_hosts
from masp.native_profiles import list_profiles, profile_form, save_profile
from masp.storage import Store


def test_upstream_schema_and_form_save_validate_and_rollback(tmp_path):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    plugin = tmp_path / "settings.mjs"
    plugin.write_text("""import S from '@deepseek-ai/schemastery';
export const name='settings-fixture';
export const Config=S.object({label:S.string().required(),
enabled:S.boolean().default(true),count:S.number().min(1).default(2)});
export function apply(ctx,config){};
""")
    config = json.dumps(
        [{"id": "settings", "name": plugin.as_uri(), "config": {"label": "original"}}]
    )
    try:
        save_profile(store, home, "form", config, "[]")
        form = profile_form(store, home, "form")
        assert form["schema"]["x-cordis"]["complete"]
        assert form["entries"][0]["config"]["label"] == "original"
        assert form["schema"]["x-cordis"]["entries"][0]["configRef"]
        profile_form(
            store, home, "form", [{"id": "settings", "config": {"label": "edited", "count": 3}}]
        )
        assert profile_form(store, home, "form")["entries"][0]["config"]["label"] == "edited"
        with pytest.raises(ValueError, match="changed since"):
            profile_form(
                store,
                home,
                "form",
                [{"id": "settings", "config": {"label": "stale"}}],
                form["revision"],
            )
        before = list_profiles(store, home)
        with pytest.raises((ValueError, RuntimeError)):
            profile_form(
                store,
                home,
                "form",
                [{"id": "settings", "config": {"label": "invalid", "count": -1}}],
            )
        assert list_profiles(store, home) == before
    finally:
        close_native_hosts(store)


def test_form_keeps_env_expressions_unevaluated_when_editing_other_fields(tmp_path):
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    directory = home / "native-profiles" / "expressions"
    directory.mkdir(parents=True)
    (directory / ".env").write_text("CONFIG_LABEL=fixture-private-value\n")
    plugin = tmp_path / "expressions.mjs"
    plugin.write_text("""import S from '@deepseek-ai/schemastery';
export const name='expression-fixture';
export const Config=S.object({label:S.string().required(),count:S.number().min(1)});
export function apply(ctx,config){};
""")
    config = (
        "- id: settings\n  name: "
        + plugin.as_uri()
        + "\n  config:\n    label: !!js process.env.CONFIG_LABEL\n    count: 2\n"
    )
    try:
        save_profile(store, home, "expressions", config, "[]")
        form = profile_form(store, home, "expressions")
        values = form["entries"][0]["config"]
        assert "fixture-private-value" not in json.dumps(values)
        values["count"] = 3
        profile_form(
            store, home, "expressions", [{"id": "settings", "config": values}], form["revision"]
        )
        patch = (directory / "cordis.patch.yml").read_text()
        assert "!!js" in patch and "process.env.CONFIG_LABEL" in patch
        assert "fixture-private-value" not in patch
    finally:
        close_native_hosts(store)
