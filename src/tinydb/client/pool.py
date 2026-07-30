"""Connection pool for the synchronous Python Client (v0.3, T-3.8).

A :class:`Pool` wraps up to ``max_size`` :class:`Client` instances and
hands them out via :meth:`acquire` (blocking) / :meth:`release`.  The
pool is intentionally simple: a :class:`queue.Queue` holds idle
clients; new clients are created on demand up to the cap.
"""
from __future__ import annotations

import queue
import threading
from contextlib import contextmanager
from typing import Iterator, List, Optional

from tinydb.client.sync import Client


class Pool:
    """Thread-safe pool of :class:`tinydb.client.sync.Client` objects."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        max_size: int = 4,
        database: Optional[str] = None,
        **client_kwargs,
    ) -> None:
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        self._host = host
        self._port = port
        self._database = database
        self._max_size = max_size
        self._client_kwargs = client_kwargs
        self._idle: "queue.Queue[Client]" = queue.Queue(maxsize=max_size)
        self._all_clients: List[Client] = []
        self._lock = threading.Lock()
        self._closed = False

    def _make_client(self) -> Client:
        return Client(
            self._host,
            self._port,
            database=self._database,
            **self._client_kwargs,
        )

    def acquire(self, timeout: Optional[float] = None) -> Client:
        """Acquire a client from the pool.

        If the idle queue is non-empty we reuse an existing client.
        Otherwise — and if we are still below ``max_size`` — we open
        a fresh connection.  Once the cap is reached we block up to
        ``timeout`` seconds for a client to be released back to the
        pool (``timeout=None`` blocks forever).
        """
        if self._closed:
            raise RuntimeError("pool is closed")
        # Fast path: non-blocking pull from the idle queue.
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass
        # Slow path: maybe we can grow.
        with self._lock:
            if self._closed:
                raise RuntimeError("pool is closed")
            if len(self._all_clients) < self._max_size:
                c = self._make_client()
                self._all_clients.append(c)
                return c
        # Cap reached — wait for a release.
        return self._idle.get(timeout=timeout)

    def release(self, client: Client) -> None:
        """Return a client to the pool.

        The client is put back on the idle queue.  If the pool is full
        or already closed, the client is closed instead.
        """
        if self._closed:
            try:
                client.close()
            except Exception:
                pass
            return
        try:
            self._idle.put_nowait(client)
        except queue.Full:
            try:
                client.close()
            except Exception:
                pass

    @contextmanager
    def connection(self, timeout: Optional[float] = None) -> Iterator[Client]:
        """Acquire a client inside a ``with`` block; auto-release on exit.

        On exception the client is closed instead of being recycled
        because we don't know if the protocol stream is still healthy.
        """
        client = self.acquire(timeout=timeout)
        try:
            yield client
        except Exception:
            try:
                client.close()
            finally:
                self._forget(client)
            raise
        else:
            self.release(client)

    def _forget(self, client: Client) -> None:
        """Remove a bad client from the bookkeeping list."""
        with self._lock:
            try:
                self._all_clients.remove(client)
            except ValueError:
                pass

    def close(self) -> None:
        """Close all clients and refuse new acquires."""
        with self._lock:
            self._closed = True
        # Drain idle queue.
        while True:
            try:
                c = self._idle.get_nowait()
            except queue.Empty:
                break
            try:
                c.close()
            except Exception:
                pass
        # Close everything we know about.
        with self._lock:
            for c in list(self._all_clients):
                try:
                    c.close()
                except Exception:
                    pass
                self._all_clients.remove(c)

    def __enter__(self) -> "Pool":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = ["Pool"]