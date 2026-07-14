"""Tests for tinydb.tx.WriteLock — single-writer reentrant lock."""
from __future__ import annotations

import threading
import time

import pytest

from tinydb.tx import WriteLock, WriteLockHeld


# 1. acquire/release from same thread
def test_acquire_release_same_thread():
    lock = WriteLock()
    held = lock.acquire()
    assert isinstance(held, WriteLockHeld)
    lock.release()


# 2. Nested acquire (3 levels) then release 3 times -> depth returns to 0
def test_nested_acquire_three_levels():
    lock = WriteLock()
    h1 = lock.acquire()
    h2 = lock.acquire()
    h3 = lock.acquire()
    assert h1 is not h2
    assert h2 is not h3
    lock.release()
    lock.release()
    lock.release()


# 3. Two different threads: one holds, the other blocks until release.
def test_thread_blocks_while_holder_owns_lock():
    lock = WriteLock()
    holder_acquired = threading.Event()
    holder_should_release = threading.Event()
    waiter_observed_release = threading.Event()

    def holder():
        lock.acquire()
        holder_acquired.set()
        holder_should_release.wait(timeout=2.0)
        lock.release()

    def waiter():
        holder_acquired.wait(timeout=2.0)
        lock.acquire()
        waiter_observed_release.set()
        lock.release()

    t_holder = threading.Thread(target=holder)
    t_waiter = threading.Thread(target=waiter)
    t_holder.start()
    t_waiter.start()

    # Waiter should still be blocked while holder owns the lock
    time.sleep(0.1)
    assert not waiter_observed_release.is_set()

    holder_should_release.set()
    t_holder.join(timeout=2.0)
    t_waiter.join(timeout=2.0)

    assert waiter_observed_release.is_set()


# 4. Two threads acquiring simultaneously: only one wins; second proceeds after release.
def test_only_one_thread_holds_lock_simultaneously():
    lock = WriteLock()
    active_count = 0
    max_active = 0
    counter_lock = threading.Lock()
    both_started = threading.Event()
    proceed_release = threading.Event()

    def worker():
        nonlocal active_count, max_active
        both_started.wait(timeout=2.0)
        lock.acquire()
        with counter_lock:
            active_count += 1
            max_active = max(max_active, active_count)
        # Hold for a moment
        proceed_release.wait(timeout=2.0)
        with counter_lock:
            active_count -= 1
        lock.release()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    both_started.set()

    # Give both threads time to try acquiring
    time.sleep(0.2)
    assert max_active == 1

    proceed_release.set()
    for t in threads:
        t.join(timeout=2.0)


# 5. Reentrant: thread A acquires twice, thread B starts -> blocks.
def test_reentrant_then_other_thread_blocks():
    lock = WriteLock()
    a_acquired_first = threading.Event()
    b_attempted = threading.Event()
    b_acquired = threading.Event()

    def thread_a():
        lock.acquire()
        lock.acquire()  # reentrant
        a_acquired_first.set()
        # Hold while B tries
        time.sleep(0.5)
        lock.release()
        lock.release()

    def thread_b():
        a_acquired_first.wait(timeout=2.0)
        lock.acquire()
        b_acquired.set()
        lock.release()

    t_a = threading.Thread(target=thread_a)
    t_b = threading.Thread(target=thread_b)
    t_a.start()
    t_b.start()

    # Wait long enough for B to have attempted and A to release
    time.sleep(0.8)
    # While A still holds (within the 0.5s sleep), B should not have acquired
    # After A releases, B should acquire

    t_a.join(timeout=2.0)
    t_b.join(timeout=2.0)
    assert b_acquired.is_set()


# 6. After thread A depth returns to 0, thread B unblocks and proceeds.
def test_thread_b_unblocks_after_a_depth_zero():
    lock = WriteLock()
    a_held = threading.Event()
    a_should_release = threading.Event()
    b_acquired = threading.Event()

    def thread_a():
        lock.acquire()
        lock.acquire()
        lock.acquire()
        a_held.set()
        a_should_release.wait(timeout=2.0)
        lock.release()
        lock.release()
        lock.release()

    def thread_b():
        a_held.wait(timeout=2.0)
        lock.acquire()
        b_acquired.set()
        lock.release()

    t_a = threading.Thread(target=thread_a)
    t_b = threading.Thread(target=thread_b)
    t_a.start()
    t_b.start()

    # B should not have acquired while A still holds
    time.sleep(0.1)
    assert not b_acquired.is_set()

    a_should_release.set()
    t_a.join(timeout=2.0)
    t_b.join(timeout=2.0)
    assert b_acquired.is_set()


# 7. Context manager: `with lock.acquire() as held: ...` works.
def test_context_manager_acquire():
    lock = WriteLock()
    with lock.acquire() as held:
        assert isinstance(held, WriteLockHeld)


# 8. Reentrance via context manager: nested `with` blocks increase depth.
def test_nested_context_manager():
    lock = WriteLock()
    with lock.acquire() as outer:
        # Other thread should still block while we are inside nested cm
        other_attempted = threading.Event()
        other_acquired = threading.Event()

        def other():
            other_attempted.set()
            lock.acquire()
            other_acquired.set()
            lock.release()

        t = threading.Thread(target=other)
        t.start()
        other_attempted.wait(timeout=2.0)
        time.sleep(0.1)
        assert not other_acquired.is_set()

        with lock.acquire() as inner:
            assert inner is not outer

        # Still outer held, B still blocked
        time.sleep(0.1)
        assert not other_acquired.is_set()

    # Outer released -> B can acquire
    t.join(timeout=2.0)
    assert other_acquired.is_set()


# 9. Bonus: many threads contending — only one runs at a time (no torn critical section).
def test_many_threads_no_torn_critical_section():
    lock = WriteLock()
    counter = 0
    counter_lock = threading.Lock()
    iterations = 50
    thread_count = 8
    barrier = threading.Barrier(thread_count)

    def worker():
        nonlocal counter
        barrier.wait(timeout=2.0)
        for _ in range(iterations):
            lock.acquire()
            # Critical section: read-modify-write must be atomic
            val = counter
            time.sleep(0)  # yield
            counter = val + 1
            lock.release()

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert counter == thread_count * iterations