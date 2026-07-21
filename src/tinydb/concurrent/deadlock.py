"""Wait-for-graph deadlock detector.

The transaction manager registers every cross-transaction lock wait
via :meth:`DeadlockDetector.add_wait`. Each node is a transaction id
(an integer). Edges ``waiter -> holder`` mean "waiter is blocked
waiting for holder to release its lock". A cycle in this directed
graph means the waiters are mutually blocked: a deadlock.

Detection algorithm
-------------------
A simple recursive DFS that tracks the *path* (not just visited
nodes) in a list. If during traversal we reach a node already on
the path, a cycle exists: the slice from that node to the end of
the path is the cycle. We return the highest-id node in any
detected cycle (the "youngest", which is the natural rollback
victim per D-6).

Why not a per-edge timeout?
---------------------------
A timeout-based fallback is a reasonable second line of defense but
requires choosing a threshold; the wait-for-graph detector is exact
and O(V + E) per call, which is fine when the active transaction set
is small (typical for embedded use).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set


class DeadlockDetector:
    """Tracks ``waiter -> holder`` edges and reports cycle victims.

    Edge direction: ``waits_for[waiter] = holder`` means ``waiter`` is
    blocked because ``holder`` holds a needed lock. A cycle ``A -> B
    -> A`` indicates A is waiting for B and B is waiting for A.
    """

    __slots__ = ("_waits_for",)

    def __init__(self) -> None:
        # waiter -> holder (one outgoing edge per waiter — a thread
        # waits on one lock at a time in this design).
        self._waits_for: Dict[int, int] = {}

    # -- mutation ------------------------------------------------------

    def add_wait(self, waiter: int, holder: int) -> None:
        """Register ``waiter`` as blocked on ``holder``."""
        self._waits_for[waiter] = holder

    def remove(self, tx_id: int) -> None:
        """Drop any edges involving ``tx_id`` (called on commit/rollback)."""
        self._waits_for.pop(tx_id, None)
        # Also drop any waiter that was pointing at this holder —
        # those waits are now moot.
        stale = [w for w, h in self._waits_for.items() if h == tx_id]
        for w in stale:
            self._waits_for.pop(w, None)

    def has_edge(self, waiter: int) -> bool:
        """``True`` iff ``waiter`` is currently waiting on someone."""
        return waiter in self._waits_for

    # -- query ---------------------------------------------------------

    def detect_cycle(self) -> Optional[int]:
        """Return the id of a transaction in a cycle, or ``None``.

        When multiple cycles exist, returns the highest transaction id
        in any cycle (the "youngest", which is the natural rollback
        candidate per the design decision D-6).
        """
        if not self._waits_for:
            return None
        victim = 0
        for start in self._waits_for:
            cycle = self._dfs_cycle(start, [])
            if cycle is not None:
                if max(cycle) > victim:
                    victim = max(cycle)
        return victim or None

    # -- internals -----------------------------------------------------

    def _dfs_cycle(self, node: int, path: List[int]) -> Optional[List[int]]:
        """Recursive DFS returning the cycle node list, or ``None``.

        ``path`` is the current DFS path (a list). Reaching a node
        already on the path closes a cycle: the slice from the
        cycle-opening node onward (plus the cycle-closing node) is
        the cycle. Returns ``None`` when no cycle is reachable from
        ``node`` in this DFS branch.
        """
        if node in path:
            # Cycle: extract the slice from the first occurrence of
            # ``node`` in ``path`` to the end, and append ``node`` to
            # close the loop.
            idx = path.index(node)
            return path[idx:] + [node]
        holder = self._waits_for.get(node)
        if holder is None:
            return None
        path.append(node)
        result = self._dfs_cycle(holder, path)
        path.pop()
        return result


__all__ = ["DeadlockDetector"]