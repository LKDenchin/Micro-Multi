import copy
import json
import shutil
from pathlib import Path

import pytest

from masp.cordis_runtime import close_native_hosts
from masp.extension_config import bundle_configuration
from masp.plugin_tools import discover_plugins, execute_plugin, install_dsh_plugin_from_path
from masp.storage import Store


def test_configuration_updates_real_tool_and_rejects_stale_revision(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(Path(__file__).parents[1] / "examples/native-cordis", source)
    home = tmp_path / "home"
    store = Store(home / "store.sqlite3")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    try:
        bundle = install_dsh_plugin_from_path(store, home, str(source))
        form = bundle_configuration(store, home, bundle["id"])
        entries = copy.deepcopy(form["entries"])
        counter = next(entry for entry in entries if "counter" in entry["name"])
        counter["config"]["start"] = 40
        bundle_configuration(store, home, bundle["id"], entries, form["revision"])
        tool = next(iter(discover_plugins(store)[1].values()))
        assert (
            json.loads(execute_plugin(tool, '{"label":"configured"}', workspace, store))["value"]
            == 41
        )
        with pytest.raises(ValueError, match="配置已变化"):
            bundle_configuration(store, home, bundle["id"], entries, form["revision"])
        updated = bundle_configuration(store, home, bundle["id"])
        invalid = copy.deepcopy(updated["entries"])
        invalid[0]["key"] = "99"
        with pytest.raises(ValueError, match="不能替换入口"):
            bundle_configuration(store, home, bundle["id"], invalid, updated["revision"])
        assert bundle_configuration(store, home, bundle["id"])["revision"] == updated["revision"]
    finally:
        close_native_hosts(store)
