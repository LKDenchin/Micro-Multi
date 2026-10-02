import pytest

from masp.domain import TeamInput
from masp.review_policy import review_reasons


@pytest.mark.parametrize(
    "path",
    [
        "src/permissions.py",
        "src/native/host.mjs",
        "db/migrations/001.sql",
        "package.json",
        "src/session_store.py",
    ],
)
def test_critical_paths_require_review(path):
    assert review_reasons({path: ""}) == [path]


def test_ordinary_artifacts_skip_independent_review_but_sensitive_code_does_not():
    assert (
        review_reasons(
            {"web/styles.css": "body { color: blue }", "src/add.py": "def add(a,b): return a+b"}
        )
        == []
    )
    assert review_reasons({"src/utils.py": "lock = asyncio.Lock()"}) == ["src/utils.py"]
    assert TeamInput.model_fields["review_mode"].default == "adaptive"
