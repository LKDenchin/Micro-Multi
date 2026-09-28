from pathlib import Path

import pytest

from masp.service import Service


@pytest.fixture
def service(tmp_path: Path):
    instance = Service(tmp_path / "home")
    yield instance
    instance.close()
