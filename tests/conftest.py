"""pytest only: the same safety net tests/run.py puts under every run (state, models and radar in a temp dir)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "utils"))

import run  # noqa: E402

_undo = run.isolate_user_state()


def pytest_unconfigure(config):
    _undo()
