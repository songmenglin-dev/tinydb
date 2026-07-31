"""tinydb-server main module (v0.3, T-2.4, REQ-SRV-1, REQ-SRV-5).

Provides:

* :func:`run_server` — an async coroutine that starts an asyncio
  TCP server bound to the configured host/port.  Used by the CLI
  entry point and by tests.
* :func:`main` — the blocking entry point for the ``tinydb-server``
  console script.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Callable, Optional

from tinydb.api import Database
from tinydb.server.config import ServerConfig
from tinydb.server.session import ServerSession

logger = logging.getLogger("tinydb.server")


# ``_shutdown_event`` is created lazily inside :func:`main` so it
# binds to the dedicated event loop the server actually runs on,
# rather than to whatever loop happened to be current at import time
# (which on a freshly-imported module would be no loop at all — and
# in test runners that touch the loop early can be a loop the
# server never sees).
_shutdown_event: Optional[asyncio.Event] = None


async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    db: Database,
) -> None:
    """Per-connection coroutine: hand off to a :class:`ServerSession`."""
    session = ServerSession(db=db)
    await session.serve(reader, writer)


async def run_server(
    config: ServerConfig,
    db: Optional[Database] = None,
    on_ready: Optional[Callable[[], None]] = None,
) -> asyncio.base_events.Server:
    """Start the server and return the asyncio ``Server`` object.

    The caller can ``await server.serve_forever()`` to keep it running
    or ``server.close()`` to shut it down.  Tests pass ``on_ready`` to
    be notified the moment the socket is bound.
    """
    if db is None:
        db = Database(config.db_path)
    server = await asyncio.start_server(
        lambda r, w: _handle_connection(r, w, db),
        host=config.host,
        port=config.port,
        limit=65536,
    )
    logger.info("listening on %s:%d", config.host, config.port)
    if on_ready is not None:
        on_ready()
    return server


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Register SIGINT/SIGTERM → graceful shutdown."""
    def _stop() -> None:
        global _shutdown_event
        logger.info("shutdown signal received")
        if _shutdown_event is not None:
            _shutdown_event.set()

    # Module-level wrappers instead of inline lambdas: lambdas create
    # a new closure each call which (a) prevents signal.signal() from
    # correctly unregistering a previous handler and (b) can re-enter
    # mid-handler if the signal fires twice on Windows.
    def _sigint_handler(*_args) -> None:
        _stop()

    def _sigterm_handler(*_args) -> None:
        _stop()

    for sig, handler in (
        (signal.SIGINT, _sigint_handler),
        (signal.SIGTERM, _sigterm_handler),
    ):
        try:
            loop.add_signal_handler(sig, handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler.
            signal.signal(sig, handler)


def main(argv: Optional[list] = None) -> int:
    """Synchronous entry point for the ``tinydb-server`` command."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="tinydb-server",
        description="tinydb-server: a tiny asyncio TCP server for the tinydb protocol.",
    )
    parser.add_argument("--db-path", required=True, help="Path to the .db file to serve.")
    parser.add_argument("--host", "-H", default="127.0.0.1", help="Bind host (default 127.0.0.1).")
    parser.add_argument("--port", "-p", type=int, default=8520, help="Bind port (default 8520).")
    parser.add_argument("--max-conns", type=int, default=64, help="Maximum concurrent connections.")
    parser.add_argument("--heartbeat-interval", type=float, default=30.0, help="Heartbeat interval seconds.")
    args = parser.parse_args(argv)

    # Disable the default signal handler so our custom one wins.
    logging.basicConfig(level=logging.INFO, format="[server] %(asctime)s %(levelname)s %(message)s")

    config = ServerConfig(
        db_path=args.db_path,
        host=args.host,
        port=args.port,
        max_conns=args.max_conns,
        heartbeat_interval=args.heartbeat_interval,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    _install_signal_handlers(loop)

    async def _serve():
        db = Database(config.db_path)
        server = await run_server(config, db=db)
        try:
            assert _shutdown_event is not None  # for type checkers
            await _shutdown_event.wait()
        finally:
            server.close()
            await server.wait_closed()
            db.close()

    try:
        loop.run_until_complete(_serve())
    except OSError as e:
        print(f"[server] bind error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    finally:
        loop.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["run_server", "main"]
