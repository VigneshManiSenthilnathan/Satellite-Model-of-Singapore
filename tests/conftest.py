"""Tests run in synthetic mode by default (P0.7), so they never touch Bloomberg.

Live tests are marked ``@pytest.mark.bloomberg``; run them on a Terminal machine with
    SMS_SYNTHETIC=0 python -m pytest -m bloomberg
"""

import os

import pytest

os.environ.setdefault("SMS_SYNTHETIC", "1")

from data.panel import synthetic_mode  # noqa: E402


def pytest_collection_modifyitems(config, items):
    if not synthetic_mode():
        return
    skip = pytest.mark.skip(reason="needs Bloomberg; run with SMS_SYNTHETIC=0")
    for item in items:
        if "bloomberg" in item.keywords:
            item.add_marker(skip)
