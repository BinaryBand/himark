import subprocess
import sys
from pathlib import Path

# Hypothesis is an optional test dependency. If it's not installed the test
# discovery/import phase should still succeed; only enable Hypothesis settings
# when the package is available.
try:
    from hypothesis import settings

    # Disable Hypothesis deadline in tests to avoid flaky timeouts on slow machines
    settings.register_profile("no_deadline", deadline=None)
    settings.load_profile("no_deadline")
    HAS_HYPOTHESIS = True
except Exception:
    HAS_HYPOTHESIS = False

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _tool(name: str) -> str:
    """Resolve a tool to its venv path, falling back to the bare name."""
    candidate = Path(sys.executable).parent / name
    return str(candidate) if candidate.exists() else name


def pytest_sessionstart() -> None:
    _run_check(_tool("ruff"), "format", ".")
    _run_check(_tool("ruff"), "check", "--fix", ".")
    _run_check(_tool("ty"), "check", "--fix")


def _run_check(*cmd: str) -> None:
    label = " ".join(cmd)
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    except FileNotFoundError:
        print(f"\n[{label}] skipped (not found)")
        return
    if result.stdout.strip():
        print(f"\n[{label}]\n{result.stdout.strip()}")
    if result.returncode != 0:
        print(f"\n[{label}] exited {result.returncode}")
        if result.stderr.strip():
            print(result.stderr.strip())
