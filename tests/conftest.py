from pathlib import Path

import pytest

_TESTS = Path(__file__).parent


def pytest_collection_modifyitems(items):
    """Mark tests by level from their directory, so `-m unit` / `-m integration` work."""
    for item in items:
        path = Path(item.fspath)
        if _TESTS / "unit" in path.parents:
            item.add_marker(pytest.mark.unit)
        elif _TESTS / "integration" in path.parents:
            item.add_marker(pytest.mark.integration)
