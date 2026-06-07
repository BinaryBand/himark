try:
    from hypothesis import settings

    # Disable Hypothesis deadline in tests to avoid flaky timeouts on slow machines
    settings.register_profile("no_deadline", deadline=None)
    settings.load_profile("no_deadline")
except Exception:
    # Hypothesis not installed; tests that require it will skip via importorskip
    pass


def pytest_configure(config):
    # keep pytest configuration hook simple for future extensions
    pass


# Ensure repository root is on sys.path so tests can import the package in-place
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
