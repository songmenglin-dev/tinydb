"""Query executor — Plan tree + dispatch.

T-5.1 exposes the Plan dataclasses and the ``plan()`` AST translator;
T-5.2..5.6 implement the row-producing executors.
"""

from tinydb.executor.executor import Executor
from tinydb.executor.ops import (
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
    "plan",
    "Plan",
    "SeqScan",
    "IndexScan",
    "Filter",
    "Project",
    "Sort",
    "Limit",
    "Insert",
    "Update",
    "Delete",
]