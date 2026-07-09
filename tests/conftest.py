"""Shared test fixtures for the tinydb test suite.

Fixtures defined here are intentionally minimal in Batch 1; later batches
add ``Database``-level fixtures that depend on modules created in those
batches.
"""

import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    """Path to a fresh, non-existent file inside pytest's tmp dir.

    Tests use this as the target of ``tinydb.open(...)``. The file is
    not created up-front; opening the database creates it.
    """
    return tmp_path / "test.db"
