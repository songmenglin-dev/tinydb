"""Test fixtures for the tinydb v0.2 JOIN worktree.

Adds the worktree's ``src/`` directory to ``sys.path`` so tests pick
up THIS worktree's modules (the editable install is shared across
worktrees and currently points elsewhere).
"""
import sys
from pathlib import Path

# Resolve absolute path to this worktree's src/ — added at front of path
# so it shadows any other tinydb installation.
_THIS_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_THIS_SRC) not in sys.path:
    sys.path.insert(0, str(_THIS_SRC))

import pytest  # noqa: E402


@pytest.fixture
def tmp_db_path(tmp_path):
    """Path to a fresh, non-existent file inside pytest's tmp dir."""
    return tmp_path / "test.db"
