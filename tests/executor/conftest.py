"""Shared fixtures for executor tests.

T-5.1 deliberately avoids the public ``open_db`` API (lands in B7) and
the not-yet-existing ``tinydb.storage.engine.Engine`` wrapper — instead
it spins up a :class:`Pager` directly and binds a :class:`Catalog` to
it.  This matches the pattern used in ``tests/storage/test_catalog.py``
and keeps T-5.1 self-contained.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from tinydb.storage.catalog import Catalog
from tinydb.storage.pager import Pager
from tinydb.types.system import Column, TypeTag


@pytest.fixture
def catalog(tmp_path) -> Iterator[Catalog]:
    """A fresh :class:`Catalog` backed by a tmp :class:`Pager`.

    Yields the catalog and ensures the pager is closed on teardown.
    """
    pager = Pager.open(tmp_path / "test.db")
    try:
        yield Catalog(pager)
    finally:
        pager.close()


def _col(name: str, tag: TypeTag, **kw) -> Column:
    return Column(name=name, tag=tag, **kw)


@pytest.fixture
def users_catalog(catalog: Catalog) -> Catalog:
    """Catalog with a ``users(id INT PK, name TEXT, age INT)`` table."""
    catalog.create_table(
        "users",
        [
            _col("id", TypeTag.Int, primary_key=True),
            _col("name", TypeTag.Text),
            _col("age", TypeTag.Int),
        ],
    )
    return catalog