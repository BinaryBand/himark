"""Pytest configuration.

Note: formatting and type-checking are deliberately *not* run here. Tests must
not mutate the working tree as a side effect of collection — that belongs in
pre-commit / CI. Run `ruff format . && ruff check . && ty check` yourself.
"""

import sys
from pathlib import Path

# Hypothesis is an optional test dependency. When present, disable its deadline
# so property tests don't flake on slow machines.
try:
    from hypothesis import settings

    settings.register_profile("no_deadline", deadline=None)
    settings.load_profile("no_deadline")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    """`HIMARK_RUST=1 pytest` runs the whole suite on the native backend (which
    falls back to Python for unsupported patterns), to confirm parity end-to-end.
    Off by default — PythonEngine stays the backend."""
    import os

    if os.environ.get("HIMARK_RUST"):
        from himark.engine import RUST_AVAILABLE, RustEngine, set_backend

        if not RUST_AVAILABLE:
            raise RuntimeError("HIMARK_RUST set but himark_rs is not built")
        set_backend(RustEngine())
