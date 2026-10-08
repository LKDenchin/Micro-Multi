import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "site_build", Path(__file__).resolve().parents[1] / "scripts/build_site.py"
)
assert spec and spec.loader
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


def metadata(version):
    names = [
        f"Micro-Multi-Setup-{version}-x64.exe",
        f"Micro-Multi-{version}-amd64.deb",
        f"Micro-Multi-{version}-x86_64.AppImage",
        "SHA256SUMS.txt",
    ]
    return {
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": name,
                "state": "uploaded",
                "browser_download_url": f"{site.REPO}/releases/download/v{version}/{name}",
            }
            for name in names
        ],
    }


@pytest.mark.parametrize("version", ["0.2.0", "1.12.3"])
def test_homepages_use_all_actual_release_asset_urls(version):
    release = metadata(version)
    links = site.release_downloads(release)
    for chinese in [False, True]:
        page = site.landing(chinese, links)
        assert all(asset["browser_download_url"] in page for asset in release["assets"])
        assert "/releases/download/v0.1.0/" not in page


def test_missing_assets_use_latest_release_page():
    release = metadata("0.2.0")
    release["assets"] = release["assets"][:1]
    page = site.landing(True, site.release_downloads(release))
    assert "Micro-Multi-Setup-0.2.0-x64.exe" in page
    assert f'href="{site.REPO}/releases/latest"' in page
    assert ".AppImage" not in page
    assert "Release 文件" in page


@pytest.mark.parametrize("problem", ["draft", "prerelease", "duplicate", "external_url"])
def test_rejects_unpublished_or_ambiguous_metadata(problem):
    release = metadata("0.2.0")
    if problem in {"draft", "prerelease"}:
        release[problem] = True
    elif problem == "duplicate":
        release["assets"].append(release["assets"][0])
    else:
        release["assets"][0]["browser_download_url"] = "https://example.com/installer.exe"
    with pytest.raises(ValueError):
        site.release_downloads(release)
