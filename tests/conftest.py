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
    HAS_HYPOTHESIS = True
except Exception:
    HAS_HYPOTHESIS = False

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
