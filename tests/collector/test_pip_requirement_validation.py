"""F-COL-031: Pip requirement strings must be validated before argv passthrough.

If central (or a pack) is compromised, a requirement like
`--index-url http://evil/ pkg` would redirect pip's whole install session.
The whitelist blocks argv flags, URLs, VCS refs, and editable installs.
"""

from __future__ import annotations

import pytest

from monctl_collector.apps.manager import _validate_requirements


@pytest.mark.parametrize(
    "req",
    [
        "requests",
        "requests==2.31.0",
        "requests>=2.28,<3",
        "pysnmp~=6.0",
        "pydantic[email]==2.5.0",
        "django-extensions",
        "Pillow>=10",
        "numpy!=1.24.0",
    ],
)
def test_accepts_safe_requirements(req: str) -> None:
    assert _validate_requirements([req]) == [req]


@pytest.mark.parametrize(
    "req",
    [
        "--index-url http://evil.com/",
        "-e git+https://github.com/evil/pkg.git",
        "git+https://github.com/evil/pkg.git",
        "https://evil.com/pkg.whl",
        "file:///tmp/evil.whl",
        "requests; python_version < '3.11'",
        "pkg --config-setting key=value",
        "../../../etc/passwd",
        "pkg@http://evil.com/mal.whl",
        "",
    ],
)
def test_rejects_unsafe_requirements(req: str) -> None:
    if req == "":
        assert _validate_requirements([req]) == []
        return
    with pytest.raises(RuntimeError, match="Rejected pip requirement"):
        _validate_requirements([req])


def test_rejects_first_bad_entry_wholly() -> None:
    with pytest.raises(RuntimeError):
        _validate_requirements(["requests", "-rX"])


def test_strips_whitespace_and_skips_blanks() -> None:
    assert _validate_requirements(["  requests==2.31.0  ", "", "  "]) == [
        "requests==2.31.0"
    ]
