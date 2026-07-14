"""T-5.3 — IndexScan integration tests.

Each test builds a real :class:`Catalog` + :class:`Heap` +
:class:`IndexManager` on a tmp :class:`Pager`, inserts rows through the
heap, populates the index via :meth:`IndexManager.on_insert`, and runs a
SELECT through :class:`Executor`.  Asserts on the returned rows AND on
the shape of the planned tree (so we know the planner chose
:class:`IndexScan` instead of :class:`SeqScan` when an index applies).
"""

from __future__ import annotations

import pytest

from tinydb.executor.ops import IndexScan, SeqScan
from tinydb.executor.planner import Executor, plan
from tinydb.index.manager import IndexManager
from tinydb.sql.parser import parse_dml_string as parse
from tinydb.storage.heap import Heap
from tinydb.storage.pager import Pager
from tinydb.types.codec import encode_row
from tinydb.types.system import Column, TypeTag


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _col(name: str, tag: TypeTag, **kw) -> Column:
    return Column(name=name, tag=tag, **kw)


def _tags(meta):
    return tuple(c.tag for c in meta.columns)


def _build_catalog_with_users(pager: Pager):
    """A fresh :class:`Catalog` with a ``users`` table (id PK, name, age)."""
    from tinydb.storage.catalog import Catalog

    cat = Catalog(pager)
    cat.create_table(
        "users",
        [
            _col("id", TypeTag.Int, primary_key=True),
            _col("name", TypeTag.Text),
            _col("age", TypeTag.Int),
        ],
    )
    return cat


def _seed_rows(cat, rows, mgr: IndexManager | None = None):
    """Insert ``rows`` into the heap and yield ``(rid, decoded_row)``.

    Uses :func:`encode_row` to wire each tuple through the codec so the
    heap bytes match what the executor reads back.  Returns a list of
    ``(rid, tuple)`` and the bound :class:`Heap` for caller-side reuse.

    When ``mgr`` is provided, every insert also drives
    :meth:`IndexManager.on_insert` so the index stays in sync with the
    heap (T-5.3 tests use this directly; T-5.5 will wire it from the
    INSERT plan).
    """
    meta = cat.get_table("users")
    heap = Heap(cat._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid
    out = []
    for r in rows:
        rid = heap.insert(encode_row(r, _tags(meta)))
        if mgr is not None:
            mgr.on_insert("users", rid, r)
        out.append((rid, r))
    return out, heap


def _plan_and_execute(cat, sql: str, indexer: IndexManager | None = None):
    """Plan + execute a SELECT, returning ``(plan, rows)``.

    ``indexer`` is forwarded to :func:`plan` so the planner can pick
    :class:`IndexScan` over :class:`SeqScan` when applicable.
    """
    stmt = parse(sql)
    p = plan(stmt, cat, indexer=indexer)
    executor = Executor(cat, pager=cat._pager, indexer=indexer)
    return p, executor.execute(p)


def _find_index_scan(plan_tree):
    """Recursively search a plan tree for the first :class:`IndexScan`."""
    # Stack-based traversal; avoids importing the executor package's
    # internal helpers.
    stack = [plan_tree]
    while stack:
        node = stack.pop()
        if isinstance(node, IndexScan):
            return node
        # Wrappers carry ``src``; descend.
        src = getattr(node, "src", None)
        if src is not None:
            stack.append(src)
    return None


# ---------------------------------------------------------------------------
# 1. unique index + WHERE id = 7  →  IndexScan chosen
# ---------------------------------------------------------------------------


def test_unique_index_drives_index_scan(tmp_path):
    """`WHERE id = 7` over a UNIQUE index on id → IndexScan."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_id", "users", ("id",), unique=True)

        _seed_rows(
            cat, [(1, "alice", 30), (7, "carol", 40), (9, "eve", 50)], mgr
        )

        plan_tree, rows = _plan_and_execute(
            cat, "SELECT * FROM users WHERE id = 7", indexer=mgr
        )

        idx = _find_index_scan(plan_tree)
        assert idx is not None, "planner did not pick IndexScan"
        assert idx.table == "users"
        assert idx.index == "idx_users_id"
        assert rows == [(7, "carol", 40)]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 2. same query WITHOUT an index  →  SeqScan (no IndexScan in the tree)
# ---------------------------------------------------------------------------


def test_no_index_falls_back_to_seq_scan(tmp_path):
    """`WHERE id = 7` with no index → no IndexScan anywhere in the tree."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        _seed_rows(cat, [(1, "alice", 30), (7, "carol", 40), (9, "eve", 50)])

        plan_tree, rows = _plan_and_execute(
            cat, "SELECT * FROM users WHERE id = 7"
        )

        assert _find_index_scan(plan_tree) is None
        assert rows == [(7, "carol", 40)]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 3. WHERE age >= 18 over a non-unique index  →  IndexScan range lo
# ---------------------------------------------------------------------------


def test_range_lower_bound_uses_index(tmp_path):
    """`WHERE age >= 18` with an index on age → IndexScan with lo=18."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_age", "users", ("age",))

        _seed_rows(
            cat,
            [
                (1, "kid1", 12),
                (2, "teen", 17),
                (3, "adult1", 25),
                (4, "adult2", 40),
            ],
            mgr,
        )

        plan_tree, rows = _plan_and_execute(
            cat, "SELECT * FROM users WHERE age >= 18", indexer=mgr
        )

        idx = _find_index_scan(plan_tree)
        assert idx is not None
        assert idx.lo == 18
        assert idx.lo_inclusive is True
        # Default hi/hi_inclusive — no upper bound.
        assert idx.hi is None
        # Result rows are in B-tree key order (age asc).
        assert sorted(rows, key=lambda r: r[2]) == rows
        assert rows == [(3, "adult1", 25), (4, "adult2", 40)]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 4. AND of same-column bounds  →  range scan
# ---------------------------------------------------------------------------


def test_and_same_column_uses_index_range(tmp_path):
    """`WHERE age >= 18 AND age <= 30` → range IndexScan."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_age", "users", ("age",))

        _seed_rows(
            cat,
            [
                (1, "kid", 12),
                (2, "teen", 17),
                (3, "young_adult", 25),
                (4, "mid", 30),
                (5, "old", 60),
            ],
            mgr,
        )

        plan_tree, rows = _plan_and_execute(
            cat,
            "SELECT * FROM users WHERE age >= 18 AND age <= 30",
            indexer=mgr,
        )

        idx = _find_index_scan(plan_tree)
        assert idx is not None
        assert idx.lo == 18 and idx.lo_inclusive is True
        assert idx.hi == 30 and idx.hi_inclusive is True
        assert sorted(rows, key=lambda r: r[2]) == rows
        assert rows == [(3, "young_adult", 25), (4, "mid", 30)]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 5. IndexManager.on_insert populates the index; SELECT returns the row
# ---------------------------------------------------------------------------


def test_index_populated_by_on_insert_returns_correct_row(tmp_path):
    """After heap.insert + on_insert, `WHERE name = 'alice'` returns the row."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_name", "users", ("name",))

        rows, _ = _seed_rows(
            cat,
            [
                (1, "alice", 30),
                (2, "bob", 25),
                (3, "carol", 40),
            ],
        )
        # Seed the index for each row.
        for rid, r in rows:
            mgr.on_insert("users", rid, r)

        plan_tree, result = _plan_and_execute(
            cat, "SELECT * FROM users WHERE name = 'alice'", indexer=mgr
        )

        idx = _find_index_scan(plan_tree)
        assert idx is not None
        assert idx.index == "idx_users_name"
        assert result == [(1, "alice", 30)]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 6. on_delete removes the entry — search returns []
# ---------------------------------------------------------------------------


def test_on_delete_clears_index_entry(tmp_path):
    """After on_delete, the deleted row's key no longer matches."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_id", "users", ("id",), unique=True)

        rows, _ = _seed_rows(
            cat,
            [
                (1, "alice", 30),
                (2, "bob", 25),
            ],
            mgr,
        )

        # Delete the bob row (id=2).
        bob_rid, bob_row = rows[1]
        mgr.on_delete("users", bob_rid, bob_row)

        # The unique index should no longer surface id=2.
        idx = mgr.get_by_name("idx_users_id")
        assert idx is not None
        assert idx.search(2) == []

        # And a SELECT via the executor reflects that.
        plan_tree, result = _plan_and_execute(
            cat, "SELECT * FROM users WHERE id = 2", indexer=mgr
        )
        assert _find_index_scan(plan_tree) is not None
        assert result == []
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 7. on_update with a new key: old key returns [], new key returns the row
# ---------------------------------------------------------------------------


def test_on_update_reindexes_old_and_new_key(tmp_path):
    """`on_update` removes the old key and inserts the new key.

    The test exercises the index maintenance side only — the heap
    row's bytes aren't rewritten (T-5.5 will own that).  After
    on_update the new key points at alice's rid; we verify the B-tree
    directly rather than via the executor (because the heap still
    holds the old row bytes).
    """
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_name", "users", ("name",))

        rows, _ = _seed_rows(
            cat,
            [
                (1, "alice", 30),
                (2, "bob", 25),
            ],
            mgr,
        )

        alice_rid, alice_old = rows[0]
        alice_new = (1, "alicia", 30)  # name changed
        mgr.on_update("users", alice_rid, alice_old, alice_new)

        idx = mgr.get_by_name("idx_users_name")
        assert idx is not None
        assert idx.search("alice") == []
        assert idx.search("alicia") == [alice_rid]
        # Also: a SELECT with WHERE name = 'alice' returns nothing.
        plan_tree, result = _plan_and_execute(
            cat, "SELECT * FROM users WHERE name = 'alice'", indexer=mgr
        )
        assert _find_index_scan(plan_tree) is not None
        assert result == []
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 8. NULL key  →  planner falls back (NULLs are not in the B-tree)
# ---------------------------------------------------------------------------


def test_null_key_falls_back_to_seq_scan(tmp_path):
    """`WHERE age IS NULL` does NOT use the index — planner returns SeqScan."""
    from tinydb.storage.catalog import Catalog

    pager = Pager.open(tmp_path / "test.db")
    try:
        # Build a table whose indexed column IS nullable (TypeTag.Null).
        cat = Catalog(pager)
        cat.create_table(
            "users",
            [
                _col("id", TypeTag.Int, primary_key=True),
                _col("name", TypeTag.Text),
                _col("age", TypeTag.Null),
            ],
        )
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_age", "users", ("age",))

        meta = cat.get_table("users")
        heap = Heap(cat._pager, table_id=meta.table_id)
        heap._head_pid = meta.heap_pid
        tags = tuple(c.tag for c in meta.columns)
        alice_rid = heap.insert(encode_row((1, "alice", None), tags))
        nobody_rid = heap.insert(encode_row((2, "nobody", None), tags))
        mgr.on_insert("users", alice_rid, (1, "alice", None))
        mgr.on_insert("users", nobody_rid, (2, "nobody", None))

        plan_tree, result = _plan_and_execute(
            cat, "SELECT * FROM users WHERE age IS NULL", indexer=mgr
        )

        # The planner should NOT pick IndexScan here.
        assert _find_index_scan(plan_tree) is None
        # The result still contains the NULL row, fetched via SeqScan+Filter.
        assert (1, "alice", None) in result
        assert (2, "nobody", None) in result
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 9. Equality on a column NOT covered by any index  →  SeqScan
# ---------------------------------------------------------------------------


def test_equality_on_unindexed_column_uses_seq_scan(tmp_path):
    """An equality predicate on a column with no index → SeqScan + Filter."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        # Index covers `name`; the WHERE references `age` (not indexed).
        mgr.create_index("idx_users_name", "users", ("name",))
        _seed_rows(
            cat,
            [
                (1, "alice", 30),
                (2, "bob", 25),
            ],
        )

        plan_tree, rows = _plan_and_execute(
            cat, "SELECT * FROM users WHERE age = 25", indexer=mgr
        )

        assert _find_index_scan(plan_tree) is None
        assert rows == [(2, "bob", 25)]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 10. Empty heap + empty index  →  [] without crashing
# ---------------------------------------------------------------------------


def test_empty_table_with_index_returns_empty(tmp_path):
    """No rows in heap + index built but empty → query returns []."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_id", "users", ("id",), unique=True)
        # No rows inserted; the B-tree is empty but valid.

        plan_tree, rows = _plan_and_execute(
            cat, "SELECT * FROM users WHERE id = 1", indexer=mgr
        )

        idx = _find_index_scan(plan_tree)
        assert idx is not None
        assert rows == []
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# Coverage extensions — exercise the open-ended walk in IndexLookup
# ---------------------------------------------------------------------------


def test_index_lookup_open_ended_full_walk(tmp_path):
    """IndexLookup.range(lo=None, hi=None) walks every leaf in key order."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_age", "users", ("age",))

        _seed_rows(
            cat,
            [
                (1, "a", 30),
                (2, "b", 25),
                (3, "c", 40),
            ],
            mgr,
        )

        # Direct IndexLookup call — bypass the planner's bound
        # extraction and exercise the open-ended walk.
        from tinydb.executor.index_scan import IndexLookup

        idx_obj = mgr.get_by_name("idx_users_age")
        assert idx_obj is not None
        lookup = IndexLookup(mgr, idx_obj, TypeTag.Int)
        rids = sorted(rid.page_id * 1000 + rid.slot_id for rid, _ in lookup.range(None, None))
        assert len(rids) == 3
    finally:
        pager.close()


def test_index_lookup_open_low_only_walk(tmp_path):
    """range(lo=20, hi=None) returns every key >= 20 in order."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_age", "users", ("age",))

        _seed_rows(
            cat,
            [
                (1, "a", 10),
                (2, "b", 20),
                (3, "c", 30),
                (4, "d", 40),
            ],
            mgr,
        )

        from tinydb.executor.index_scan import IndexLookup

        idx_obj = mgr.get_by_name("idx_users_age")
        lookup = IndexLookup(mgr, idx_obj, TypeTag.Int)
        keys = [k for _, k in lookup.range(20, None, lo_inclusive=True)]
        assert keys == [20, 30, 40]
    finally:
        pager.close()


def test_index_lookup_open_high_only_walk(tmp_path):
    """range(lo=None, hi=30) returns every key <= 30."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_age", "users", ("age",))

        _seed_rows(
            cat,
            [
                (1, "a", 10),
                (2, "b", 20),
                (3, "c", 30),
                (4, "d", 40),
            ],
            mgr,
        )

        from tinydb.executor.index_scan import IndexLookup

        idx_obj = mgr.get_by_name("idx_users_age")
        lookup = IndexLookup(mgr, idx_obj, TypeTag.Int)
        keys = [k for _, k in lookup.range(None, 30, hi_inclusive=True)]
        assert keys == [10, 20, 30]
    finally:
        pager.close()


def test_index_lookup_strict_open_interval(tmp_path):
    """range(lo=20, hi=30, lo_inclusive=False, hi_inclusive=False) returns (20, 30).

    Closed-range lookups yield ``(rid, None)`` keys (T-5.3 contract:
    only the open-ended walker surfaces keys because BTreeIndex.range
    does not).  The rid count and ordering is the load-bearing
    assertion here.
    """
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_catalog_with_users(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_age", "users", ("age",))

        _seed_rows(
            cat,
            [
                (1, "a", 10),
                (2, "b", 20),
                (3, "c", 25),
                (4, "d", 30),
                (5, "e", 40),
            ],
            mgr,
        )

        from tinydb.executor.index_scan import IndexLookup

        idx_obj = mgr.get_by_name("idx_users_age")
        lookup = IndexLookup(mgr, idx_obj, TypeTag.Int)
        rids = list(lookup.range(20, 30, lo_inclusive=False, hi_inclusive=False))
        assert len(rids) == 1  # only (25)
        # And the equality walk gives us the matching rid with the key.
        eq = list(lookup.equality(25))
        assert len(eq) == 1
        assert eq[0][1] == 25
    finally:
        pager.close()