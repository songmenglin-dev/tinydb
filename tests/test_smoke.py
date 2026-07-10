"""Smoke tests for tinydb package import surface.

T-1.1 RED step: confirms the package is importable and exposes the
version string.  Other public-surface tests are added in T-1.2 once
``tinydb.errors`` exists, and in T-7.1 once ``tinydb.open`` exists.
"""

import tinydb


def test_package_imports():
    assert tinydb is not None


def test_version_string():
    assert tinydb.__version__ == "0.1.0"
