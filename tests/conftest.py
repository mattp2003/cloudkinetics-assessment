import pytest


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless explicitly selected with -m integration."""
    selected_markers = config.getoption("-m", default="")
    if "integration" in selected_markers:
        return
    skip = pytest.mark.skip(reason="integration test — run with -m integration")
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip)
