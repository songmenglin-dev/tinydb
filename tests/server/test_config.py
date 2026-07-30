"""Tests for ServerConfig (v0.3, T-2.1)."""
from __future__ import annotations

import pytest

from tinydb.server.config import ServerConfig


class TestServerConfigDefaults:
    """Constructing with no args yields the documented defaults."""

    def test_default_host(self):
        c = ServerConfig(db_path="/tmp/x.db")
        assert c.host == "127.0.0.1"

    def test_default_port(self):
        c = ServerConfig(db_path="/tmp/x.db")
        assert c.port == 8520

    def test_default_max_conns(self):
        c = ServerConfig(db_path="/tmp/x.db")
        assert c.max_conns == 64

    def test_default_idle_timeout(self):
        c = ServerConfig(db_path="/tmp/x.db")
        assert c.idle_timeout == 1800

    def test_default_heartbeat_interval(self):
        c = ServerConfig(db_path="/tmp/x.db")
        assert c.heartbeat_interval == 30.0

    def test_default_heartbeat_misses(self):
        c = ServerConfig(db_path="/tmp/x.db")
        assert c.heartbeat_misses == 3


class TestServerConfigOverrides:
    """Every field can be overridden."""

    def test_custom_host(self):
        c = ServerConfig(db_path="/tmp/x.db", host="0.0.0.0")
        assert c.host == "0.0.0.0"

    def test_custom_port(self):
        c = ServerConfig(db_path="/tmp/x.db", port=9527)
        assert c.port == 9527

    def test_custom_max_conns(self):
        c = ServerConfig(db_path="/tmp/x.db", max_conns=128)
        assert c.max_conns == 128


class TestServerConfigValidation:
    """Invalid values raise ValueError."""

    def test_port_zero(self):
        with pytest.raises(ValueError):
            ServerConfig(db_path="/tmp/x.db", port=0)

    def test_port_too_high(self):
        with pytest.raises(ValueError):
            ServerConfig(db_path="/tmp/x.db", port=70000)

    def test_negative_max_conns(self):
        with pytest.raises(ValueError):
            ServerConfig(db_path="/tmp/x.db", max_conns=-1)

    def test_zero_max_conns(self):
        with pytest.raises(ValueError):
            ServerConfig(db_path="/tmp/x.db", max_conns=0)

    def test_negative_heartbeat(self):
        with pytest.raises(ValueError):
            ServerConfig(db_path="/tmp/x.db", heartbeat_interval=-1.0)

    def test_zero_heartbeat_misses(self):
        with pytest.raises(ValueError):
            ServerConfig(db_path="/tmp/x.db", heartbeat_misses=0)
