"""Query executor — Plan tree + dispatch.

T-5.1 exposes the Plan dataclasses and the ``plan()`` AST translator;
T-5.2..5.6 implement the row-producing executors.
"""
from tinydb.executor.executor import Executor
from tinydb.executor.heap_bind import bind_heap
from tinydb.executor.index_plan import IndexablePredicate, extract_indexable
from tinydb.executor.index_scan import IndexLookup
from tinydb.executor.ops import (
    Aggregate,
    Delete,
    Filter,
    IndexScan,
    Insert,
    Limit,
    Plan,
    Project,
    SeqScan,
    Sort,
    Update,
)
from tinydb.executor.planner import plan

__all__ = [
    "Executor",
    "bind_heap",
    "plan",
    "Plan",
    "SeqScan",
    "IndexScan",
    "Filter",
    "Project",
    "Sort",
    "Limit",
    "Aggregate",
    "Insert",
    "Update",
    "Delete",
    "IndexLookup",
    "IndexablePredicate",
    "extract_indexable",
]