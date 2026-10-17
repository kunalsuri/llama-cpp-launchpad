#!/usr/bin/env python3
"""The one way to run the tests, on every OS (same command locally and in CI). Standard library only.

  python tests/run.py                  run everything
  python tests/run.py -k ollama        only tests whose name contains 'ollama' (repeatable)
  python tests/run.py --repeat 5       run the whole suite 5 times; any failure fails (finds flaky tests)
  python tests/run.py --failfast       stop at the first failure
  python tests/run.py --list           print the tests that would run, run nothing
  python tests/run.py --cov            measure line+branch coverage of utils/ (needs: pip install coverage)
  python tests/run.py --cov --min 85   ... and fail if coverage is below 85 %

Exit code: 0 all passed, 1 a test failed, 2 nothing ran or bad usage (zero tests is never a pass).
Syntax warnings, invalid escape sequences and FutureWarnings are errors here: they have hidden real bugs.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import unittest
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


class TimedResult(unittest.TextTestResult):
    def startTest(self, test):
        self._t0 = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        self.timings = getattr(self, "timings", [])
        self.timings.append((time.perf_counter() - self._t0, test.id()))
        super().stopTest(test)


def collect(patterns: list) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    if patterns:
        loader.testNamePatterns = [p if "*" in p else f"*{p}*" for p in patterns]
    return loader.discover(str(HERE), pattern="test_*.py", top_level_dir=str(HERE))


def flatten(suite) -> list:
    out = []
    for item in suite:
        out.extend(flatten(item) if isinstance(item, unittest.TestSuite) else [item])
    return out


def run_once(patterns: list, failfast: bool, quiet: bool) -> tuple:
    suite = collect(patterns)
    count = suite.countTestCases()
    if count == 0:
        return 2, 0
    runner = unittest.TextTestRunner(verbosity=1 if quiet else 2, failfast=failfast, resultclass=TimedResult,
                                     stream=sys.stdout)
    result = runner.run(suite)
    slow = sorted(getattr(result, "timings", []), reverse=True)[:5]
    print("\nslowest: " + ", ".join(f"{t:.1f}s {i.rsplit('.', 2)[-2]}.{i.rsplit('.', 1)[-1]}" for t, i in slow))
    return (0 if result.wasSuccessful() else 1), count


def run_with_coverage(argv: list, minimum: int) -> int:
    try:
        import coverage  # noqa: F401
    except ImportError:
        print("coverage is not installed:  python -m pip install coverage   (it is in requirements.txt)")
        return 2
    base = [sys.executable, "-m", "coverage"]
    env = dict(os.environ, COVERAGE_FILE=str(ROOT / ".coverage"))
    rc = subprocess.run(base + ["run", "--branch", f"--source={ROOT / 'utils'}", str(Path(__file__).resolve())] + argv,
                        cwd=str(ROOT), env=env).returncode
    report = subprocess.run(base + ["report", "-m"] + ([f"--fail-under={minimum}"] if minimum else []),
                            cwd=str(ROOT), env=env).returncode
    return rc or report


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the llama-cpp-launchpad tests.")
    ap.add_argument("-k", action="append", default=[], metavar="TEXT", help="only tests whose name contains TEXT")
    ap.add_argument("--repeat", type=int, default=1, metavar="N", help="run the suite N times (flaky-test hunt)")
    ap.add_argument("--failfast", action="store_true")
    ap.add_argument("--list", action="store_true", help="list the selected tests and exit")
    ap.add_argument("--quiet", "-q", action="store_true")
    ap.add_argument("--cov", action="store_true", help="measure coverage of utils/")
    ap.add_argument("--min", type=int, default=0, metavar="PCT", help="with --cov: fail below this percentage")
    args = ap.parse_args(argv)
    if args.repeat < 1:
        ap.error("--repeat must be at least 1")
    if args.cov:
        forward = [a for a in (argv if argv is not None else sys.argv[1:]) if a != "--cov"]
        if args.min:
            i = forward.index("--min")
            del forward[i:i + 2]
        return run_with_coverage(forward, args.min)

    warnings.simplefilter("default")
    for category in (SyntaxWarning, FutureWarning):
        warnings.simplefilter("error", category)
    warnings.filterwarnings("error", message="invalid escape", category=DeprecationWarning)
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(ROOT / "utils"))

    if args.list:
        names = [t.id() for t in flatten(collect(args.k))]
        print("\n".join(names))
        return 0 if names else 2
    worst, total = 0, 0
    for n in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"\n=== run {n} of {args.repeat} ===")
        rc, count = run_once(args.k, args.failfast, args.quiet)
        total += count
        worst = max(worst, rc)
        if rc and args.failfast:
            break
    print(f"\n{'PASS' if worst == 0 else 'FAIL'}: {total} test runs ({args.repeat} x suite)")
    return worst


if __name__ == "__main__":
    sys.exit(main())
