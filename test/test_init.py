"""Initial testing module."""

import contextprotector


def test_version() -> None:
    version = getattr(contextprotector, "__version__", None)
    assert version is not None
    assert isinstance(version, str)
