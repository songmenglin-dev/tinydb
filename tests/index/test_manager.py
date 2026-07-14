"""Tests for IndexManager — catalog integration, UNIQUE, persistence (T-4.6).

Covers REQ-IDX-4 (write-time index maintenance), REQ-IDX-5 (UNIQUE
constraint) and REQ-IDX-6 (cross-restart persistence).

The manager ties together the Catalog (table metadata), the BTreeIndex
(per-index storage) and the executor's write hooks. Each test exercises
a single behaviour described in the task brief; together they cover
the 12+ scenarios listed in T-4.6 / Phase 1 (RED).
"""

from __future__ import annotations

from typing import List, Tuple

import pytest

from tinydb.errors import ConstraintViolation
from tinydb.storage.catalog import Catalog
from tinydb.storage.heap import Rid
from tinydb.storage.pager import Pager
from tinydb.types.system import Column, TypeTag


# --- helpers ------------------------------------------------------------


def _col(name: str, tag, **kw) -> Column:
    return Column(name=name, tag=tag, **kw)


def _make_catalog_with_users(pager: Pager) -> Catalog:
    """Build a catalog with a single ``users(id INT, email TEXT)`` table."""
    cat = Catalog(pager)
    cat.create_table(
        "users",
        [
            _col("id", TypeTag.Int, primary_key=True),
            _col("email", TypeTag.Text),
            _col("age", TypeTag.Int),
        ],
    )
    return cat


def _make_catalog_with_composite(pager: Pager) -> Catalog:
    """Build a catalog with ``items(a TEXT, b TEXT, c INT)`` for composite indexes."""
    cat = Catalog(pager)
    cat.create_table(
        "items",
        [
            _col("a", TypeTag.Text),
            _col("b", TypeTag.Text),
            _col("c", TypeTag.Int),
        ],
    )
    return cat


# --- 1. create_index allocates a fresh page ----------------------------


def test_create_index_allocates_fresh_page(tmp_db_path):
    """create_index allocates a new page for the B-tree root_pid."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_users_email", "users", ("email",))

        # get_by_name returns the BTreeIndex (per the brief).
        idx = mgr.get_by_name("idx_users_email")
        assert idx is not None
        # The catalog exposes the IndexMeta with the root_pid.
        meta = cat.get_index("idx_users_email")
        assert meta.root_pid >= 4  # past reserved pages 0..3
        # And the manager lists it.
        assert "idx_users_email" in mgr.list_indexes()
    finally:
        p.close()


# --- 2. create_index + on_insert populates the B-tree -------------------


def test_create_index_on_insert_populates_tree(tmp_db_path):
    """After create_index, on_insert writes entries that search can find."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_users_email", "users", ("email",))

        # Indexes expose raw BTreeIndex via get_by_name.
        idx = mgr.get_by_name("idx_users_email")
        assert idx is not None
        # on_insert receives a row tuple in column order.
        rid_alice = Rid(page_id=5, slot_id=0)
        rid_bob = Rid(page_id=5, slot_id=1)
        rid_carol = Rid(page_id=5, slot_id=2)
        # users schema: (id, email, age) — values are typed per Column.
        mgr.on_insert(
            "users",
            rid_alice,
            (1, "alice@example.com", 30),
        )
        mgr.on_insert(
            "users",
            rid_bob,
            (2, "bob@example.com", 25),
        )
        mgr.on_insert(
            "users",
            rid_carol,
            (3, "carol@example.com", 40),
        )

        assert idx.search("alice@example.com") == [rid_alice]
        assert idx.search("bob@example.com") == [rid_bob]
        assert idx.search("carol@example.com") == [rid_carol]
        # Miss: returns []
        assert idx.search("nobody@example.com") == []
    finally:
        p.close()


# --- 3. create_index persists across reopen -----------------------------


def test_create_index_persists_across_reopen(tmp_db_path):
    """After close/reopen, the index is still queryable."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_users_email", "users", ("email",))
        mgr.on_insert("users", Rid(5, 0), (1, "alice@example.com", 30))
        mgr.on_insert("users", Rid(5, 1), (2, "bob@example.com", 25))
    finally:
        p.close()

    p2 = Pager.open(tmp_db_path)
    try:
        cat2 = Catalog(p2)
        mgr2 = IndexManager(cat2, p2)
        idx = mgr2.get_by_name("idx_users_email")
        assert idx is not None
        # search must still find the rows that were inserted before close
        rids = idx.search("alice@example.com")
        assert rids == [Rid(5, 0)]
        rids = idx.search("bob@example.com")
        assert rids == [Rid(5, 1)]
    finally:
        p2.close()


# --- 4. drop_index removes the entry ------------------------------------


def test_drop_index_removes_entry(tmp_db_path):
    """After drop_index, get_by_name / get return None."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_x", "users", ("email",))
        mgr.create_index("idx_y", "users", ("age",))
        assert mgr.get_by_name("idx_x") is not None
        mgr.drop_index("idx_x")
        assert mgr.get_by_name("idx_x") is None
        assert mgr.get_by_name("idx_y") is not None  # other index unaffected
        # And the get(table, columns) path is also clean.
        assert mgr.get("users", ("email",)) is None
    finally:
        p.close()


def test_drop_unknown_index_raises_keyerror(tmp_db_path):
    """drop_index on a missing name raises KeyError."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        with pytest.raises(KeyError):
            mgr.drop_index("never_existed")
    finally:
        p.close()


# --- 5. get(table, columns) returns the right index ---------------------


def test_get_by_table_and_columns_finds_match(tmp_db_path):
    """Multiple indexes on different columns — get() finds by (table, columns)."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_email", "users", ("email",))
        mgr.create_index("idx_age", "users", ("age",))

        email_idx = mgr.get("users", ("email",))
        age_idx = mgr.get("users", ("age",))
        assert email_idx is not None
        assert age_idx is not None
        assert email_idx is not age_idx

        # unknown combination returns None
        assert mgr.get("users", ("id",)) is None
    finally:
        p.close()


# --- 6. on_update keeps the index consistent ----------------------------


def test_on_update_keeps_index_consistent(tmp_db_path):
    """Update: delete old key, insert new key."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_email", "users", ("email",))
        rid = Rid(page_id=5, slot_id=0)
        mgr.on_insert("users", rid, (1, "old@example.com", 30))

        idx = mgr.get_by_name("idx_email")
        assert idx is not None
        assert idx.search("old@example.com") == [rid]

        mgr.on_update(
            "users",
            rid,
            (1, "old@example.com", 30),
            (1, "new@example.com", 30),
        )

        # Old key gone, new key present.
        assert idx.search("old@example.com") == []
        assert idx.search("new@example.com") == [rid]
    finally:
        p.close()


# --- 7. on_delete removes from index ------------------------------------


def test_on_delete_removes_from_index(tmp_db_path):
    """Delete a row: its key is no longer in the index."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_email", "users", ("email",))
        rid = Rid(page_id=5, slot_id=0)
        mgr.on_insert("users", rid, (1, "alice@example.com", 30))

        idx = mgr.get_by_name("idx_email")
        assert idx is not None
        assert idx.search("alice@example.com") == [rid]

        mgr.on_delete("users", rid, (1, "alice@example.com", 30))
        assert idx.search("alice@example.com") == []
    finally:
        p.close()


# --- 8. UNIQUE rejects duplicate insert ---------------------------------


def test_unique_rejects_duplicate_insert(tmp_db_path):
    """UNIQUE: second insert with same key raises ConstraintViolation."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index(
            "idx_users_email_unique", "users", ("email",), unique=True
        )

        rid_a = Rid(page_id=5, slot_id=0)
        rid_b = Rid(page_id=5, slot_id=1)
        mgr.on_insert("users", rid_a, (1, "dup@example.com", 30))
        with pytest.raises(ConstraintViolation):
            mgr.on_insert("users", rid_b, (2, "dup@example.com", 40))
    finally:
        p.close()


def test_unique_allows_different_keys(tmp_db_path):
    """UNIQUE: two different keys both insert cleanly."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_email_u", "users", ("email",), unique=True)
        mgr.on_insert("users", Rid(5, 0), (1, "a@example.com", 30))
        mgr.on_insert("users", Rid(5, 1), (2, "b@example.com", 31))
        idx = mgr.get_by_name("idx_email_u")
        assert idx is not None
        assert len(idx.search("a@example.com")) == 1
        assert len(idx.search("b@example.com")) == 1
    finally:
        p.close()


# --- 9. UNIQUE allows NULL ----------------------------------------------


def test_unique_allows_null(tmp_db_path):
    """UNIQUE: multiple rows with NULL in the indexed column all succeed.

    Per REQ-IDX-5 NULL does not participate in the unique check, so a
    second (or third) insert of NULL must not raise.  v0.1 does not
    index NULL keys — they simply are not added to the B-tree — so a
    subsequent ``search(None)`` returns ``[]``.
    """
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_email_u", "users", ("email",), unique=True)

        # Three rows whose email is NULL — each should insert cleanly.
        mgr.on_insert("users", Rid(5, 0), (1, None, 30))
        mgr.on_insert("users", Rid(5, 1), (2, None, 31))
        mgr.on_insert("users", Rid(5, 2), (3, None, 32))
        # No exception raised — that's the contract.
        idx = mgr.get_by_name("idx_email_u")
        assert idx is not None
        # NULL keys are not indexed in v0.1 — search returns [].
        assert idx.search(None) == []
    finally:
        p.close()


# --- 10. Composite index ------------------------------------------------


def test_composite_index_range_by_prefix(tmp_db_path):
    """Composite (a, b): range((x,), (x,)) returns entries with a == x."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_composite(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_ab", "items", ("a", "b"))

        rid1 = Rid(6, 0)
        rid2 = Rid(6, 1)
        rid3 = Rid(6, 2)
        rid4 = Rid(6, 3)
        mgr.on_insert("items", rid1, ("x", "1", 10))
        mgr.on_insert("items", rid2, ("x", "2", 20))
        mgr.on_insert("items", rid3, ("y", "1", 30))
        mgr.on_insert("items", rid4, ("x", "3", 40))

        idx = mgr.get_by_name("idx_ab")
        assert idx is not None
        x_rids = list(idx.range(("x",), ("x",), inclusive=True))
        # x-prefix has three entries (order independent — Rid is not
        # naturally orderable).
        assert set(x_rids) == {rid1, rid2, rid4}
    finally:
        p.close()


# --- 11. list_indexes filters by table ---------------------------------


def test_list_indexes_filters_by_table(tmp_db_path):
    """list_indexes(table=...) returns only indexes for that table."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = Catalog(p)
        cat.create_table(
            "users", [_col("id", TypeTag.Int), _col("email", TypeTag.Text)]
        )
        cat.create_table(
            "orders", [_col("id", TypeTag.Int), _col("sku", TypeTag.Text)]
        )
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_u_email", "users", ("email",))
        mgr.create_index("idx_o_sku", "orders", ("sku",))

        all_idx = mgr.list_indexes()
        assert sorted(all_idx) == ["idx_o_sku", "idx_u_email"]
        assert mgr.list_indexes("users") == ["idx_u_email"]
        assert mgr.list_indexes("orders") == ["idx_o_sku"]
        # unknown table returns []
        assert mgr.list_indexes("missing") == []
    finally:
        p.close()


# --- 12. Multiple indexes on the same table -----------------------------


def test_multiple_indexes_on_same_table(tmp_db_path):
    """Two indexes on different columns of the same table: on_insert updates both."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_email", "users", ("email",))
        mgr.create_index("idx_age", "users", ("age",))

        rid = Rid(page_id=5, slot_id=0)
        mgr.on_insert("users", rid, (1, "alice@example.com", 30))

        email_idx = mgr.get_by_name("idx_email")
        age_idx = mgr.get_by_name("idx_age")
        assert email_idx is not None
        assert age_idx is not None
        # Both indexes are populated.
        assert email_idx.search("alice@example.com") == [rid]
        assert age_idx.search(30) == [rid]
    finally:
        p.close()


# --- 13. Persistence of UNIQUE flag -------------------------------------


def test_unique_flag_persists_across_reopen(tmp_db_path):
    """After close/reopen, UNIQUE index still rejects duplicates."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index(
            "idx_email_u", "users", ("email",), unique=True
        )
        mgr.on_insert("users", Rid(5, 0), (1, "x@example.com", 30))
    finally:
        p.close()

    p2 = Pager.open(tmp_db_path)
    try:
        cat2 = Catalog(p2)
        mgr2 = IndexManager(cat2, p2)
        # The unique index on disk still rejects duplicates.
        with pytest.raises(ConstraintViolation):
            mgr2.on_insert("users", Rid(5, 1), (2, "x@example.com", 31))
    finally:
        p2.close()


# --- 14. create_index with duplicate name raises ValueError -------------


def test_create_index_duplicate_name_raises(tmp_db_path):
    """create_index with an already-used name raises ValueError."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        mgr.create_index("idx_dup", "users", ("email",))
        with pytest.raises(ValueError):
            mgr.create_index("idx_dup", "users", ("age",))
    finally:
        p.close()


def test_create_index_on_unknown_table_raises(tmp_db_path):
    """create_index for a non-existent table raises KeyError."""
    from tinydb.index.manager import IndexManager

    p = Pager.open(tmp_db_path)
    try:
        cat = _make_catalog_with_users(p)
        mgr = IndexManager(cat, p)
        with pytest.raises(KeyError):
            mgr.create_index("idx_x", "no_such_table", ("email",))
    finally:
        p.close()


# --- 15. IndexMeta is frozen and slots ----------------------------------


def test_index_meta_is_frozen():
    """IndexMeta is a frozen dataclass — assignments raise FrozenInstanceError."""
    import dataclasses

    from tinydb.index.manager import IndexMeta

    meta = IndexMeta(
        name="idx_x",
        table="users",
        columns=("email",),
        root_pid=4,
        unique=False,
    )
    # Sanity: shape matches
    field_names = {f.name for f in dataclasses.fields(meta)}
    assert field_names == {"name", "table", "columns", "root_pid", "unique"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        meta.name = "other"  # type: ignore[misc]
    # columns is a tuple.
    assert isinstance(meta.columns, tuple)