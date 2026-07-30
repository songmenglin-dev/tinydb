"""Server configuration (v0.3, T-2.1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Union


@dataclass
class ServerConfig:
    """Configuration for a :class:`tinydb.server.app.run_server` call.

    Defaults match the scenario in REQ-SRV-1:

    * host: ``127.0.0.1``
    * port: ``8520``
    * max_conns: ``64``
    * idle_timeout: ``1800`` seconds
    * heartbeat_interval: ``30.0`` seconds (set lower in tests)
    * heartbeat_misses: ``3``
    """

    db_path: Union[str, Path]
    host: str = "127.0.0.1"
    port: int = 8520
    max_conns: int = 64
    idle_timeout: int = 1800
    heartbeat_interval: float = 30.0
    heartbeat_misses: int = 3

    def __post_init__(self) -> None:
        if not self.db_path:
            raise ValueError("db_path is required")
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"port must be 1..65535, got {self.port}")
        if self.max_conns < 1:
            raise ValueError(f"max_conns must be >= 1, got {self.max_conns}")
        if self.heartbeat_interval <= 0:
            raise ValueError(
                f"heartbeat_interval must be > 0, got {self.heartbeat_interval}"
            )
        if self.heartbeat_misses < 1:
            raise ValueError(
                f"heartbeat_misses must be >= 1, got {self.heartbeat_misses}"
            )
        if self.idle_timeout < 0:
            raise ValueError(
                f"idle_timeout must be >= 0, got {self.idle_timeout}"
            )

    def as_dict(self) -> dict:
        """Return a JSON-friendly snapshot of the config."""
        return {
            "db_path": str(self.db_path),
            "host": self.host,
            "port": self.port,
            "max_conns": self.max_conns,
            "idle_timeout": self.idle_timeout,
            "heartbeat_interval": self.heartbeat_interval,
            "heartbeat_misses": self.heartbeat_misses,
        }


__all__ = ["ServerConfig"]
