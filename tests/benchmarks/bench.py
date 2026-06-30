"""Engine benchmark suite -- compares wall-clock speed of all five sandbox engines.

Usage::

    python tests/benchmarks/bench.py                          # all engines, all workloads
    python tests/benchmarks/bench.py --workload pipelines     # golden pipelines only
    python tests/benchmarks/bench.py --workload scaling       # bubble_sort + dedup at various sizes
    python tests/benchmarks/bench.py --engines go,rust        # subset of engines
    python tests/benchmarks/bench.py --n 3 --warmup 1         # quick smoke check

Results are always written to tests/benchmarks/results/latest.json and a timestamped
copy alongside it.  Use --output to redirect to a different directory.

Engines must be pre-compiled.  Run ``pytest tests/ -q`` first (the conftest
hook builds all binaries), or build manually:

    cargo build --release  (in sandbox/rust/)
    javac -d sandbox/build/java sandbox/engine.java
    go build -o sandbox/build/go/himark-engine sandbox/engine.go
    g++ -std=c++17 -O2 -o sandbox/build/cpp/himark-engine sandbox/engine.cpp
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from himark import parser  # noqa: E402
from himark.engine import _runner  # noqa: E402

SCRIPTS = ROOT / "himark" / "scripts"
RESOURCES = ROOT / "tests" / "demos" / "resources"
SANDBOX = ROOT / "sandbox"
RESULTS_DIR = ROOT / "tests" / "benchmarks" / "results"

ALL_ENGINES = ["go", "rust", "java", "python", "cpp"]

_BINARIES: dict[str, Path] = {
    "go": SANDBOX / "build" / "go" / "himark-engine",
    "rust": SANDBOX / "rust" / "target" / "release" / "himark-engine",
    "java": SANDBOX / "build" / "java" / "engine.class",
    "cpp": SANDBOX / "build" / "cpp" / "himark-engine",
}

# Scaling parameters
_BUBBLE_SIZES = [10, 25, 50, 100, 200]
_DEDUP_ROWS = [5, 10, 25]
_RNG_SEED = 42


def _check_engine(name: str, explicit: bool) -> bool:
    if name == "python":
        return True
    path = _BINARIES[name]
    if path.exists():
        return True
    msg = f"[bench] {name}: binary not found at {path}"
    if explicit:
        print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)
    print(
        f"WARNING: {msg} -- skipping (run 'pytest tests/ -q' to build)", file=sys.stderr
    )
    return False


# ── Workload loaders ──────────────────────────────────────────────────────────


def _load_golden_workloads() -> list[tuple[str, list, str]]:
    """The 7 golden pipelines from test_golden.PIPELINES."""
    from tests.test_golden import PIPELINES  # noqa: PLC0415

    out = []
    for name, script, resource, slice_fn in PIPELINES:
        pipeline = parser.load_script(str(SCRIPTS / script))
        raw = (RESOURCES / resource).read_text("utf-8")
        out.append((name, pipeline, slice_fn(raw)))
    return out


def _bubble_sort_input(n: int, order: str) -> str:
    """Comma-separated integers 1..n in the requested order."""
    rng = random.Random(_RNG_SEED)
    nums = list(range(1, n + 1))
    if order == "rev":
        nums.reverse()
    elif order == "rnd":
        rng.shuffle(nums)
    # "fwd" is already ascending -- one pass of the sort, best case
    return ",".join(str(x) for x in nums)


def _dedup_input(n_rows: int) -> str:
    """First n_rows data rows from podcasts.csv (header included)."""
    lines = (RESOURCES / "podcasts.csv").read_text("utf-8").splitlines(keepends=True)
    header = lines[0]
    return header + "".join(lines[1 : n_rows + 1])


def _load_scaling_workloads() -> list[tuple[str, list, str]]:
    """bubble_sort and dedup at various sizes and difficulties."""
    bs_pipeline = parser.load_script(str(SCRIPTS / "bubble_sort.hmk"))
    dedup_pipeline = parser.load_script(str(SCRIPTS / "dedup.hmk"))

    out: list[tuple[str, list, str]] = []

    for n in _BUBBLE_SIZES:
        for order in ("rev", "rnd", "fwd"):
            label = f"bs/{order}-{n:03d}"
            out.append((label, bs_pipeline, _bubble_sort_input(n, order)))

    for n in _DEDUP_ROWS:
        label = f"dedup/{n:03d}rows"
        out.append((label, dedup_pipeline, _dedup_input(n)))

    return out


# ── Measurement ───────────────────────────────────────────────────────────────


def _measure(
    engine: str, pipeline: list, target: str, n: int, warmup: int
) -> list[float]:
    os.environ["HMK_ENGINE"] = engine
    for _ in range(warmup):
        _runner.run_pipeline(pipeline, target)
    times: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        _runner.run_pipeline(pipeline, target)
        times.append((time.perf_counter() - t0) * 1000.0)
    return times


# ── Output ────────────────────────────────────────────────────────────────────


def _col_width(results: list[dict]) -> int:
    return max(18, max(len(r["workload"]) for r in results) if results else 18)


def _print_table(results: list[dict]) -> None:
    w = _col_width(results)
    header = f"  {'Workload':<{w}}  {'Engine':<8}  {'Mean ms':>8}  {'Min ms':>7}  {'Max ms':>7}  {'Stdev':>7}"
    sep = (
        "  "
        + "-" * w
        + "  "
        + "-" * 8
        + "  "
        + "-" * 8
        + "  "
        + "-" * 7
        + "  "
        + "-" * 7
        + "  "
        + "-" * 7
    )

    workload_order = list(dict.fromkeys(r["workload"] for r in results))
    print()
    print(header)
    print(sep)
    for wl in workload_order:
        rows = sorted(
            [r for r in results if r["workload"] == wl],
            key=lambda r: r["mean_ms"],
        )
        for r in rows:
            print(
                f"  {r['workload']:<{w}}  {r['engine']:<8}"
                f"  {r['mean_ms']:>8.1f}  {r['min_ms']:>7.1f}"
                f"  {r['max_ms']:>7.1f}  {r['stdev_ms']:>7.1f}"
            )

    print()
    print("  Summary (mean across all workloads, fastest first):")
    print(sep)
    engine_means: dict[str, list[float]] = {}
    for r in results:
        engine_means.setdefault(r["engine"], []).append(r["mean_ms"])
    summary = sorted(
        [(e, statistics.mean(ms)) for e, ms in engine_means.items()],
        key=lambda x: x[1],
    )
    slowest = summary[-1][1]
    for engine, mean in summary:
        speedup = slowest / mean if mean > 0 else float("inf")
        print(f"  {engine:<8}  {mean:>8.1f} ms avg   ({speedup:.1f}x vs slowest)")
    print()


def _write_results(results: list[dict], n: int, warmup: int, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc)
    payload = {
        "timestamp": ts.isoformat(),
        "n": n,
        "warmup": warmup,
        "results": results,
    }
    body = json.dumps(payload, indent=2) + "\n"

    latest = out_dir / "latest.json"
    latest.write_text(body, "utf-8")

    stamp = ts.strftime("%Y-%m-%dT%H-%M-%S")
    stamped = out_dir / f"{stamp}.json"
    stamped.write_text(body, "utf-8")

    print(f"[bench] results written to {latest} (copy: {stamped.name})")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark himark sandbox engines")
    ap.add_argument(
        "--workload",
        choices=["pipelines", "scaling", "all"],
        default="all",
        help="workload set: pipelines (7 golden), scaling (bubble_sort+dedup at varied sizes), all (default)",
    )
    ap.add_argument(
        "--engines",
        default=",".join(ALL_ENGINES),
        help="comma-separated engines (default: all)",
    )
    ap.add_argument(
        "--n",
        type=int,
        default=10,
        metavar="N",
        help="timed iterations per cell (default: 10)",
    )
    ap.add_argument(
        "--warmup",
        type=int,
        default=3,
        metavar="W",
        help="untimed warm-up iterations (default: 3)",
    )
    ap.add_argument(
        "--output",
        metavar="DIR",
        default=str(RESULTS_DIR),
        help=f"directory for result files (default: {RESULTS_DIR})",
    )
    args = ap.parse_args()

    requested = [e.strip() for e in args.engines.split(",") if e.strip()]
    explicit = args.engines != ",".join(ALL_ENGINES)
    engines = [e for e in requested if _check_engine(e, explicit)]
    if not engines:
        print("No engines available. Exiting.", file=sys.stderr)
        sys.exit(1)

    print("[bench] loading workloads...", end=" ", flush=True)
    workloads: list[tuple[str, list, str]] = []
    if args.workload in ("pipelines", "all"):
        workloads += _load_golden_workloads()
    if args.workload in ("scaling", "all"):
        workloads += _load_scaling_workloads()
    print(f"{len(workloads)} workloads loaded")
    print(f"[bench] engines: {', '.join(engines)},  n={args.n},  warmup={args.warmup}")

    results: list[dict] = []
    for engine in engines:
        for name, pipeline, target in workloads:
            print(f"  {engine:<8}  {name}...", end=" ", flush=True)
            try:
                times = _measure(engine, pipeline, target, args.n, args.warmup)
            except Exception as exc:
                print(f"ERROR: {exc}")
                continue
            mean = statistics.mean(times)
            stdev = statistics.stdev(times) if len(times) > 1 else 0.0
            results.append(
                {
                    "engine": engine,
                    "workload": name,
                    "mean_ms": round(mean, 3),
                    "min_ms": round(min(times), 3),
                    "max_ms": round(max(times), 3),
                    "stdev_ms": round(stdev, 3),
                    "times_ms": [round(t, 3) for t in times],
                }
            )
            print(f"{mean:.1f} ms")

    _print_table(results)
    _write_results(results, args.n, args.warmup, Path(args.output))


if __name__ == "__main__":
    main()
