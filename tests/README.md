# Tests

One command, same on Windows, macOS, Linux and in CI (standard library only):

```
python tests/run.py                 # everything
python tests/run.py -k ollama       # tests whose name contains "ollama"
python tests/run.py --repeat 5      # run the suite 5 times: any random failure fails (flaky-test hunt)
python tests/run.py --as mac        # pretend to be another machine: mac, mac-intel, linux, linux-arm
python tests/run.py --list          # what would run
python tests/run.py --cov --min 85  # line + branch coverage of utils/ (pip install coverage)
```

`scripts/unix/test.sh` and `scripts\win\dev-test.ps1` (pytest in `.venv`) wrap the same suite. Exit code 0 = all passed,
1 = a test failed, 2 = nothing ran (zero tests is never a pass).

## How we work: test first

Every change, new feature or fix, goes through the same loop:

1. **Red.** Write the test that describes the behaviour. Run it. Watch it fail *for the right reason*.
   A test you never saw fail proves nothing.
2. **Green.** Write the least code that makes it pass.
3. **Refactor.** Clean up with the tests green. Run `python tests/run.py --repeat 3` before you commit.

A bug fix starts with a test that reproduces the bug (see `test_refused_post_with_a_body_is_answered_cleanly`).

`test_harness.py` enforces the rules mechanically: every `utils/*.py` has a `tests/test_<name>.py`, every `/api/...`
route is exercised by a test, every launcher exists for all three OSes, no source triggers a SyntaxWarning, skips need a
reason, and CI runs on all three OSes. `test_source_audit.py` guards what the code may do (imports, programs, hosts, writes).

## Tools

- `fakes.py`: `FakeProbe`, a whole fake computer (virtual files, PATH, program output, record of programs run) so
  Windows, macOS and Linux paths are tested on any host and nothing real is executed.
- `page_harness.js`: runs the setup page's real script under Node with a fake DOM, fetch and timers, so page behaviour
  (screens, polling, Back) is tested without a browser. Skipped, with a reason, if Node is not installed.
- `fixtures/`: canned Hugging Face responses, a `/proc/meminfo`, benchmark output.
- Tests that start the real server use a random localhost port; none needs network, GPU or llama.cpp.

CI (`.github/workflows/ci.yml`) runs the suite 3x on {ubuntu, macos, windows} x {Python 3.10, 3.13}, plus coverage.
