"""Tests for the Catalog — schema persistence into reserved page 1.

T-2.4 RED phase.  Covers REQ-STO-6: schemas are written on create_table,
removed on drop_table, and survive a process restart.
"""

from __future__ import annotations

import dataclasses

import pytest

from tinydb.storage.catalog import Catalog, TableId, TableMeta
from tinydb.storage.pager import Pager
from tinydb.types.system import Column, TypeTag


# --- helpers ------------------------------------------------------------


def _col(name: str, tag, **kw) -> Column:
    return Column(name=name, tag=tag, **kw)


# --- value type immutability --------------------------------------------


def test_table_meta_is_frozen():
    """TableMeta is a frozen dataclass — assignments raise FrozenInstanceError."""
    meta = TableMeta(
        table_id=1,
        name="users",
        columns=(_col("id", TypeTag.Int),),
        heap_pid=4,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        meta.name = "other"  # type: ignore[misc]


def test_table_meta_columns_are_tuple_not_list():
    """columns is an immutable sequence (tuple), not list."""
    meta = TableMeta(
        table_id=1,
        name="users",
        columns=(_col("id", TypeTag.Int),),
        heap_pid=4,
    )
    assert isinstance(meta.columns, tuple)


# --- core behaviour -----------------------------------------------------


def test_create_table_records_metadata(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        cat = Catalog(p)
        tid = cat.create_table(
            "users",
            [
                _col("id", TypeTag.Int, primary_key=True),
                _col("name", TypeTag.Text),
            ],
        )
        meta = cat.get_table("users")
        assert meta.table_id == tid
        assert meta.name == "users"
        assert len(meta.columns) == 2
        assert meta.columns[0].name == "id"
        assert meta.columns[1].name == "name"
        assert meta.columns[0].primary_key is True
    finally:
        p.close()


def test_table_id_is_unique_per_create(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        cat = Catalog(p)
        tid_a = cat.create_table("a", [_col("x", TypeTag.Int)])
        tid_b = cat.create_table("b", [_col("y", TypeTag.Int)])
        assert tid_a != tid_b
    finally:
        p.close()


def test_list_tables_returns_all_created(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        cat = Catalog(p)
        cat.create_table("users", [_col("id", TypeTag.Int)])
        cat.create_table("orders", [_col("id", TypeTag.Int)])
        cat.create_table("products", [_col("sku", TypeTag.Text)])
        assert sorted(cat.list_tables()) == ["orders", "products", "users"]
    finally:
        p.close()


def test_get_unknown_table_raises_keyerror(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        cat = Catalog(p)
        cat.create_table("users", [_col("id", TypeTag.Int)])
        with pytest.raises(KeyError):
            cat.get_table("nope")
    finally:
        p.close()


def test_drop_table_removes_it(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        cat = Catalog(p)
        cat.create_table("users", [_col("id", TypeTag.Int)])
        cat.drop_table("users")
        assert "users" not in cat.list_tables()
        with pytest.raises(KeyError):
            cat.get_table("users")
    finally:
        p.close()


def test_drop_unknown_table_raises_keyerror(tmp_db_path):
    p = Pager.open(tmp_db_path)
    try:
        cat = Catalog(p)
        with pytest.raises(KeyError):
            cat.drop_table("never_existed")
    finally:
        p.close()


# --- persistence (REQ-STO-6) --------------------------------------------


def test_schemas_survive_restart(tmp_db_path):
    """After closing and reopening the Pager, the same tables reappear."""
    p = Pager.open(tmp_db_path)
    try:
        cat = Catalog(p)
        cat.create_table(
            "users", [_col("id", TypeTag.Int, primary_key=True), _col("name", TypeTag.Text)]
        )
        cat.create_table("orders", [_col("sku", TypeTag.Text, not_null=True)])
    finally:
        p.close()

    p2 = Pager.open(tmp_db_path)
    try:
        cat2 = Catalog(p2)
        names = sorted(cat2.list_tables())
        assert names == ["orders", "users"]
        meta = cat2.get_table("users")
        assert meta.columns[0].tag == TypeTag.Int
        assert meta.columns[0].primary_key is True
        assert meta.columns[1].tag == TypeTag.Text
    finally:
        p2.close()


def test_reopen_after_drop(tmp_db_path):
    """Drop persists — after restart the table is gone."""
    p = Pager.open(tmp_db_path)
    try:
        cat = Catalog(p)
        cat.create_table("users", [_col("id", TypeTag.Int)])
        cat.create_table("orders", [_col("id", TypeTag.Int)])
        cat.drop_table("users")
    finally:
        p.close()

    p2 = Pager.open(tmp_db_path)
    try:
        cat2 = Catalog(p2)
        assert cat2.list_tables() == ["orders"]
    finally:
        p2.close()


def test_heap_pid_is_allocated_per_table(tmp_db_path):
    """Each table gets a unique heap_pid at creation (used by Heap constructor)."""
    p = Pager.open(tmp_db_path)
    try:
        cat = Catalog(p)
        cat.create_table("a", [_col("x", TypeTag.Int)])
        cat.create_table("b", [_col("y", TypeTag.Int)])
        meta_a = cat.get_table("a")
        meta_b = cat.get_table("b")
        assert meta_a.heap_pid >= 4
        assert meta_b.heap_pid >= 4
        assert meta_a.heap_pid != meta_b.heap_pid
    finally:
        p.close()
