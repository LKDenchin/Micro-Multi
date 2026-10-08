from masp import plugin_surface
from masp.storage import Store


def test_host_only_surface_does_not_boot_host_or_hash_client(tmp_path, monkeypatch):
    store = Store(tmp_path / "store.db")
    store.put(
        "dsh_bundle",
        {
            "id": "host",
            "enabled": True,
            "name": "Host",
            "native_manifest": {"root": str(tmp_path), "client": None},
        },
    )

    def unexpected(*args, **kwargs):
        raise AssertionError("Host-only plugin must not boot for a client probe")

    monkeypatch.setattr(plugin_surface, "surface_host", unexpected)
    monkeypatch.setattr(plugin_surface, "client_revision", unexpected)
    surface = plugin_surface.surface_info(store, "host", tmp_path, conversation_only=True)
    assert surface["available"] is False
    assert surface["client_revision"] is None


def test_host_only_details_still_discover_models_and_settings(tmp_path, monkeypatch):
    from types import SimpleNamespace

    store = Store(tmp_path / "store.db")
    store.put(
        "dsh_bundle",
        {
            "id": "host",
            "enabled": True,
            "name": "Host",
            "native_manifest": {"root": str(tmp_path), "client": None},
        },
    )
    calls = []

    def request(action, **kwargs):
        calls.append(action)
        return {"providesModels": True, "settingsNamespaces": ["provider"]}

    monkeypatch.setattr(
        plugin_surface, "surface_host", lambda *args: SimpleNamespace(request=request)
    )
    surface = plugin_surface.surface_info(store, "host", tmp_path)
    assert surface["available"] is False
    assert surface["provides_models"] is True
    assert surface["settings_namespaces"] == ["provider"]
    assert calls == ["plugin-capabilities"]


def test_runtime_digest_reused_until_native_source_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_surface, "NATIVE", tmp_path)
    source = tmp_path / "host.mjs"
    source.write_text("export const version=1", encoding="utf-8")
    plugin_surface._runtime_revision.cache_clear()
    first = plugin_surface.runtime_revision()
    assert plugin_surface.runtime_revision() == first
    assert plugin_surface._runtime_revision.cache_info().hits == 1
    source.write_text("export const version=22", encoding="utf-8")
    assert plugin_surface.runtime_revision() != first
    plugin_surface._runtime_revision.cache_clear()
