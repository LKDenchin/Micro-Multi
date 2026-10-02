import pytest

from masp.extension_sources import acquire_bundle, discard_source, remote_source


@pytest.mark.parametrize(
    "source",
    ["npm:package;exit", "npm:--ignore-scripts", "git+https://name:secret@example.com/repo.git"],
)
def test_invalid_remote_sources_fail_before_execution_and_rollback(tmp_path, source):
    with pytest.raises(ValueError):
        acquire_bundle(tmp_path, source)
    assert not list((tmp_path / "extension-sources").iterdir())


def test_cleanup_cannot_escape_managed_sources(tmp_path):
    protected = tmp_path / "protected"
    protected.mkdir()
    with pytest.raises(ValueError, match="outside managed"):
        discard_source(tmp_path, protected)
    assert protected.exists()
    assert remote_source("npm:@deepseek-ai/dsh-session-turn-outline@0.2.0-rc.1")
    assert remote_source("git+https://github.com/deepseek-ai/deepseek-harness.git")
