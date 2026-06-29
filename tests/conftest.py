"""Pytest configuration."""

import sys
from pathlib import Path

try:
    from hypothesis import settings

    settings.register_profile("no_deadline", deadline=None)
    settings.load_profile("no_deadline")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
